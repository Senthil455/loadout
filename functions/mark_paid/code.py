#input_type_name: MarkPaidInput
#output_type_name: MarkPaidResult
#function_name: mark_paid

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from lemma_sdk import FunctionContext, Pod


class MarkPaidInput(BaseModel):
    settlement_id: str
    payment_ref: str = Field(
        min_length=3,
        max_length=160,
        description="Bank reference, check number, or transfer id for the payout.",
    )
    paid_at: Optional[str] = Field(
        default=None,
        description="ISO timestamp of the transfer. Defaults to now in UTC.",
    )


class MarkPaidResult(BaseModel):
    settlement_id: str
    status: str
    paid_cents: int
    payment_ref: str
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


async def mark_paid(ctx: FunctionContext, data: MarkPaidInput) -> MarkPaidResult:
    pod = Pod.from_env()
    settlement = pod.table("settlements").get(data.settlement_id)
    status = str(settlement.get("status") or "")
    approved = int(settlement.get("approved_payout_cents") or 0)
    payment_ref = data.payment_ref.strip()
    stamp = data.paid_at or _iso_now()
    actor = ctx.user_email or (str(ctx.user_id) if ctx.user_id else "unknown")

    if status == "paid":
        return MarkPaidResult(
            settlement_id=data.settlement_id,
            status=status,
            paid_cents=approved,
            payment_ref=str(settlement.get("payment_ref") or ""),
            already_recorded=True,
            message="This payout was already recorded as paid.",
        )
    if status != "approved":
        raise ValueError(
            f"Settlement is {status!r}; only an approved settlement can be marked paid."
        )
    if approved <= 0:
        raise ValueError("The approved payout must be greater than zero before it is paid.")
    if not payment_ref:
        raise ValueError("A payment reference is required.")

    pod.table("settlements").update(
        data.settlement_id,
        {
            "status": "paid",
            "paid_at": stamp,
            "payment_ref": payment_ref,
        },
    )
    _event(
        pod,
        data.settlement_id,
        "paid",
        actor,
        f"Recorded transfer of {_usd(approved)} with reference {payment_ref}.",
        stamp,
    )
    return MarkPaidResult(
        settlement_id=data.settlement_id,
        status="paid",
        paid_cents=approved,
        payment_ref=payment_ref,
        already_recorded=False,
        message="Payout recorded. The settlement is closed.",
    )
