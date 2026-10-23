#input_type_name: ReopenSettlementInput
#output_type_name: ReopenSettlementResult
#function_name: reopen_settlement

from datetime import datetime, timezone

from pydantic import BaseModel, Field
from lemma_sdk import FunctionContext, Pod


class ReopenSettlementInput(BaseModel):
    settlement_id: str
    reason: str = Field(
        min_length=5,
        max_length=400,
        description="What changed or what the next reviewer should look at.",
    )


class ReopenSettlementResult(BaseModel):
    settlement_id: str
    status: str
    review_request_id: str
    can_reopen: bool
    message: str


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


async def reopen_settlement(
    ctx: FunctionContext, data: ReopenSettlementInput
) -> ReopenSettlementResult:
    pod = Pod.from_env()
    settlement = pod.table("settlements").get(data.settlement_id)
    status = str(settlement.get("status") or "")
    reason = data.reason.strip()
    stamp = _iso_now()
    actor = ctx.user_email or (str(ctx.user_id) if ctx.user_id else "unknown")

    if status == "paid":
        raise ValueError("A paid settlement cannot be reopened. Record a new adjustment instead.")
    if status not in {"held", "approved", "draft", "awaiting_approval"}:
        raise ValueError(f"Settlement is {status!r} and cannot be reopened.")

    requests = pod.records.list_all(
        "review_requests",
        page_size=500,
        filter=[{"field": "settlement_id", "op": "eq", "value": data.settlement_id}],
    )
    open_requests = [row for row in requests if str(row.get("status")) == "open"]
    if open_requests:
        return ReopenSettlementResult(
            settlement_id=data.settlement_id,
            status=status,
            review_request_id=str(open_requests[0].get("id")),
            can_reopen=False,
            message="A review is already open for this settlement.",
        )

    pod.table("settlements").update(
        data.settlement_id,
        {
            "status": "draft",
            "approved_payout_cents": None,
            "approved_at": None,
            "approved_by": None,
            "review_note": None,
        },
    )
    request = pod.table("review_requests").create(
        {
            "settlement_id": data.settlement_id,
            "status": "open",
            "reason": reason,
            "requested_by": actor,
            "requested_at": stamp,
        }
    )
    _event(
        pod,
        data.settlement_id,
        "reopened",
        actor,
        reason,
        stamp,
    )
    return ReopenSettlementResult(
        settlement_id=data.settlement_id,
        status="draft",
        review_request_id=str(request.get("id")),
        can_reopen=True,
        message="Review reopened. The settlement desk will pick it up on the next pass.",
    )
