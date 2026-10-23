#input_type_name: AttachReviewInput
#output_type_name: AttachReviewResult
#function_name: attach_review

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from lemma_sdk import FunctionContext, Pod


class ReviewFinding(BaseModel):
    check: str
    status: Literal["pass", "watch", "block"]
    detail: str


class AttachReviewInput(BaseModel):
    review_request_id: str
    settlement_id: str
    headline: str = ""
    recommendation: Literal["approve", "hold"] = "hold"
    findings: list[ReviewFinding] = Field(default_factory=list)
    review_note: str = ""
    confidence: float | None = None


class AttachReviewResult(BaseModel):
    can_review: bool
    message: str
    settlement_id: str
    review_request_id: str
    artist: str = ""
    show_date: str = ""
    payout_cents: int = 0
    recommendation: str = ""
    reviewer_note: str = ""
    approval_member_id: str = ""
    settlement_status: str = ""


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(pod: Pod, settlement_id: str, kind: str, actor: str, detail: str, at: str) -> None:
    pod.table("settlement_events").create(
        {
            "settlement_id": settlement_id,
            "kind": kind,
            "actor": actor,
            "detail": detail,
            "occurred_at": at,
        }
    )


async def attach_review(
    ctx: FunctionContext, data: AttachReviewInput
) -> AttachReviewResult:
    pod = Pod.from_env()
    request = pod.table("review_requests").get(data.review_request_id)
    settlement = pod.table("settlements").get(data.settlement_id)
    show = pod.table("shows").get(str(settlement.get("show_id")))

    artist = str(show.get("artist") or "")
    show_date = str(show.get("show_date") or "")
    payout_cents = int(settlement.get("calculated_payout_cents") or 0)
    status = str(settlement.get("status") or "")
    stamp = _iso_now()

    def result(can_review: bool, message: str, current_status: str) -> AttachReviewResult:
        return AttachReviewResult(
            can_review=can_review,
            message=message,
            settlement_id=data.settlement_id,
            review_request_id=data.review_request_id,
            artist=artist,
            show_date=show_date,
            payout_cents=payout_cents,
            recommendation=data.recommendation,
            reviewer_note=data.review_note,
            approval_member_id="",
            settlement_status=current_status,
        )

    if str(request.get("status") or "") != "open":
        return result(False, "This review request is already closed.", status)
    if str(request.get("settlement_id") or "") != data.settlement_id:
        raise ValueError("The review request does not belong to this settlement.")

    if status in {"approved", "paid", "held"}:
        pod.table("review_requests").update(
            data.review_request_id,
            {"status": "closed", "closed_at": stamp},
        )
        _event(
            pod,
            data.settlement_id,
            "review_ready",
            "attach_review",
            (
                "Closed a review request that arrived after the payout was held."
                if status == "held"
                else "Closed a review request that arrived after the payout was already decided."
            ),
            stamp,
        )
        if status == "held":
            return result(
                False,
                "This settlement is held. Reopen it before another review.",
                status,
            )
        return result(False, "This settlement is already decided.", status)

    findings = [
        {
            "check": finding.check.strip() or "unnamed_check",
            "status": finding.status,
            "detail": finding.detail.strip() or "No detail provided.",
        }
        for finding in data.findings
    ]
    review = {
        "headline": data.headline,
        "recommendation": data.recommendation,
        "findings": findings,
        "reviewer_note": data.review_note,
        "confidence": round(float(data.confidence or 0.0), 2),
        "reviewed_at": stamp,
        "source": "settlement-reviewer",
    }
    pod.table("settlements").update(
        data.settlement_id,
        {
            "status": "awaiting_approval",
            "agent_review": review,
        },
    )
    _event(
        pod,
        data.settlement_id,
        "review_ready",
        "settlement-reviewer",
        (data.headline or "Review ready") + ". " + (data.review_note or ""),
        stamp,
    )

    settings_rows = pod.records.list_all("settings", page_size=10)
    approval_member_id = (
        str(settings_rows[0].get("approval_member_id") or "") if settings_rows else ""
    )
    out = result(True, "Review ready for approval.", "awaiting_approval")
    out.approval_member_id = approval_member_id
    return out
