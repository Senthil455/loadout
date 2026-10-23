#input_type_name: RecordReviewInput
#output_type_name: RecordReviewResult
#function_name: record_review

from datetime import datetime, timezone

from pydantic import BaseModel, Field
from lemma_sdk import FunctionContext, Pod


class RecordReviewInput(BaseModel):
    review_request_id: str
    settlement_id: str
    approved: bool
    payout_cents: int = 0
    review_note: str = ""
    decided_by: str = Field(
        default="",
        description="Email of the person who answered the form. Falls back to the run identity.",
    )


class RecordReviewResult(BaseModel):
    settlement_id: str
    status: str
    approved_payout_cents: int
    already_recorded: bool
    message: str


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _usd(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(int(cents)), 100)
    return f"{sign}${whole:,}.{part:02d}"


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


def _close_request(pod: Pod, request_id: str, at: str) -> None:
    pod.table("review_requests").update(
        request_id,
        {"status": "closed", "closed_at": at},
    )


async def record_review(
    ctx: FunctionContext, data: RecordReviewInput
) -> RecordReviewResult:
    pod = Pod.from_env()
    settlement = pod.table("settlements").get(data.settlement_id)
    request = pod.table("review_requests").get(data.review_request_id)
    status = str(settlement.get("status") or "")
    calculated = int(settlement.get("calculated_payout_cents") or 0)
    stamp = _iso_now()
    reviewer = (
        data.decided_by.strip()
        or ctx.user_email
        or (str(ctx.user_id) if ctx.user_id else "unknown")
    )

    if str(request.get("settlement_id") or "") != data.settlement_id:
        raise ValueError("The review request does not belong to this settlement.")

    if status in {"approved", "paid", "held"}:
        # A retry after a partial write, or a second form submission, converges
        # on the decision already stored instead of deciding a second time.
        if str(request.get("status") or "") == "open":
            _close_request(pod, data.review_request_id, stamp)
        if status == "held":
            message = "This payout was already held."
        elif status == "paid":
            message = "This payout was already recorded as paid."
        else:
            message = "This payout was already approved."
        return RecordReviewResult(
            settlement_id=data.settlement_id,
            status=status,
            approved_payout_cents=int(settlement.get("approved_payout_cents") or 0),
            already_recorded=True,
            message=message,
        )
    if str(request.get("status") or "") != "open":
        raise ValueError("This review request is already closed.")
    if status != "awaiting_approval":
        raise ValueError(
            f"Settlement is {status!r}; only an awaiting_approval settlement can be decided."
        )

    note = data.review_note.strip()
    if data.approved:
        payout = max(0, int(data.payout_cents))
        if payout != calculated and not note:
            raise ValueError(
                "A payout that differs from the calculated amount needs a note "
                "that explains the change."
            )
        pod.table("settlements").update(
            data.settlement_id,
            {
                "status": "approved",
                "approved_payout_cents": payout,
                "approved_at": stamp,
                "approved_by": reviewer,
                "review_note": note,
            },
        )
        _event(
            pod,
            data.settlement_id,
            "approved",
            reviewer,
            f"Payout approved at {_usd(payout)}. {note}".strip(),
            stamp,
        )
        final_status = "approved"
        final_payout = payout
        message = "Payout approved. It can be recorded as paid when the transfer clears."
    else:
        pod.table("settlements").update(
            data.settlement_id,
            {
                "status": "held",
                "approved_payout_cents": None,
                "approved_at": None,
                "approved_by": None,
                "review_note": note,
            },
        )
        _event(
            pod,
            data.settlement_id,
            "held",
            reviewer,
            note or "Payout held for another review.",
            stamp,
        )
        final_status = "held"
        final_payout = 0
        message = "Payout held. The artist is not paid until a later approval."

    _close_request(pod, data.review_request_id, stamp)
    return RecordReviewResult(
        settlement_id=data.settlement_id,
        status=final_status,
        approved_payout_cents=final_payout,
        already_recorded=False,
        message=message,
    )
