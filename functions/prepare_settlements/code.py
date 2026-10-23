#input_type_name: PrepareSettlementsInput
#output_type_name: PrepareSettlementsResult
#function_name: prepare_settlements

from datetime import date, datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
from lemma_sdk import FunctionContext, Pod


class PrepareSettlementsInput(BaseModel):
    as_of: Optional[str] = Field(
        default=None,
        description="Cut-off date in YYYY-MM-DD. Defaults to today in UTC.",
    )
    show_ids: list[str] = Field(
        default_factory=list,
        description="Optional subset of shows. Empty means every played show without a settlement.",
    )


class PreparedSettlement(BaseModel):
    settlement_id: str
    show_id: str
    artist: str
    show_date: str
    payout_cents: int
    review_request_id: str


class PrepareSettlementsResult(BaseModel):
    cycle_label: str
    prepared: int
    skipped: int
    recovered: int
    settlements: list[PreparedSettlement]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _usd(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, part = divmod(abs(int(cents)), 100)
    return f"{sign}${whole:,}.{part:02d}"


def _percent_of(amount_cents: int, basis_points: int) -> int:
    if amount_cents < 0 or basis_points < 0:
        raise ValueError("percent_of expects non-negative integers")
    return (amount_cents * basis_points + 5_000) // 10_000


def _truthy(value: object) -> bool:
    """A boolean column may arrive as bool or as a CSV-style string."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _compute(show: dict, sales: list[dict], expenses: list[dict]) -> dict:
    ticket_revenue = sum(
        int(row.get("paid_quantity") or 0) * int(row.get("face_value_cents") or 0)
        for row in sales
    )
    fees = sum(int(row.get("fees_cents") or 0) for row in sales)
    net_box_office = ticket_revenue - fees

    recoupable_total = sum(
        int(row.get("amount_cents") or 0)
        for row in expenses
        if _truthy(row.get("recoupable"))
    )
    cap = int(show.get("expense_cap_cents") or 0)
    recouped = min(recoupable_total, cap)
    over_cap = recoupable_total - recouped
    pool = max(0, net_box_office - recouped)

    deal_type = str(show.get("deal_type") or "FLAT")
    guarantee = int(show.get("guarantee_cents") or 0)
    bps = int(show.get("percentage_bps") or 0)
    share = _percent_of(pool, bps)
    if deal_type == "FLAT":
        payout = guarantee
    elif deal_type == "PERCENTAGE":
        payout = share
    elif deal_type == "VS":
        payout = max(guarantee, share)
    else:
        raise ValueError(f"unknown deal type {deal_type!r}")

    return {
        "ticket_revenue_cents": ticket_revenue,
        "fees_cents": fees,
        "net_box_office_cents": net_box_office,
        "recoupable_total_cents": recoupable_total,
        "recoup_cap_cents": cap,
        "recouped_cents": recouped,
        "over_cap_cents": over_cap,
        "pool_cents": pool,
        "deal_type": deal_type,
        "guarantee_cents": guarantee,
        "percentage_bps": bps,
        "calculated_payout_cents": payout,
    }


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


async def prepare_settlements(
    ctx: FunctionContext, data: PrepareSettlementsInput
) -> PrepareSettlementsResult:
    pod = Pod.from_env()
    now = _now()
    today = date.fromisoformat(data.as_of) if data.as_of else now.date()
    stamp = _iso(now)

    settings_rows = pod.records.list_all("settings", page_size=10)
    if not settings_rows:
        settings = pod.table("settings").create(
            {
                "venue_name": "The Lantern Room",
                "room_name": "Main Room",
                "comp_allowance": 12,
                "receipt_threshold_cents": 25_000,
                "currency": "USD",
                "activated": True,
            }
        )
    else:
        settings = settings_rows[0]

    shows = pod.records.list_all("shows", page_size=500)
    sales = pod.records.list_all("ticket_sales", page_size=1_000)
    expenses = pod.records.list_all("expenses", page_size=1_000)
    settlements = pod.records.list_all("settlements", page_size=1_000)
    requests = pod.records.list_all("review_requests", page_size=1_000)

    wanted = {str(item) for item in data.show_ids}
    by_show: dict[str, list[dict]] = {}
    for row in sales:
        by_show.setdefault(str(row.get("show_id")), []).append(row)
    expenses_by_show: dict[str, list[dict]] = {}
    for row in expenses:
        expenses_by_show.setdefault(str(row.get("show_id")), []).append(row)
    settled = {str(row.get("show_id")): row for row in settlements}
    open_requests = {
        str(row.get("settlement_id"))
        for row in requests
        if str(row.get("status")) == "open"
    }

    prepared: list[PreparedSettlement] = []
    skipped = 0
    recovered = 0

    for show in sorted(shows, key=lambda row: str(row.get("show_date") or "")):
        show_id = str(show.get("id"))
        show_day = str(show.get("show_date") or "")
        if wanted and show_id not in wanted:
            continue
        if str(show.get("status") or "") != "played":
            skipped += 1
            continue
        if not show_day or date.fromisoformat(show_day) > today:
            skipped += 1
            continue

        existing = settled.get(show_id)
        if existing is not None:
            if str(existing.get("status")) == "draft" and str(existing.get("id")) not in open_requests:
                pod.table("review_requests").create(
                    {
                        "settlement_id": str(existing.get("id")),
                        "status": "open",
                        "reason": "Recovered a draft with no open review",
                        "requested_by": "prepare_settlements",
                        "requested_at": stamp,
                    }
                )
                recovered += 1
            else:
                skipped += 1
            continue

        numbers = _compute(
            show,
            by_show.get(show_id, []),
            expenses_by_show.get(show_id, []),
        )
        settlement = pod.table("settlements").create(
            {
                "show_id": show_id,
                **numbers,
                "status": "draft",
                "agent_review": {},
                "prepared_at": stamp,
                "calculation_version": "2026-10",
            }
        )
        settlement_id = str(settlement.get("id"))
        _event(
            pod,
            settlement_id,
            "prepared",
            "prepare_settlements",
            (
                f"Computed from {len(by_show.get(show_id, []))} ticket channels and "
                f"{len(expenses_by_show.get(show_id, []))} expenses. "
                f"Calculated payout {_usd(numbers['calculated_payout_cents'])}."
            ),
            stamp,
        )
        request = pod.table("review_requests").create(
            {
                "settlement_id": settlement_id,
                "status": "open",
                "reason": f"Settlement review for {show.get('artist')} on {show_day}",
                "requested_by": "prepare_settlements",
                "requested_at": stamp,
            }
        )
        prepared.append(
            PreparedSettlement(
                settlement_id=settlement_id,
                show_id=show_id,
                artist=str(show.get("artist") or ""),
                show_date=show_day,
                payout_cents=numbers["calculated_payout_cents"],
                review_request_id=str(request.get("id")),
            )
        )

    if str(settings.get("id") or ""):
        pod.table("settings").update(str(settings.get("id")), {"last_cycle_at": stamp})

    return PrepareSettlementsResult(
        cycle_label=f"{today.isoformat()} settlement cycle",
        prepared=len(prepared),
        skipped=skipped,
        recovered=recovered,
        settlements=prepared,
    )
