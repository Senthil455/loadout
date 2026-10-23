#input_type_name: BuildReviewPacketInput
#output_type_name: BuildReviewPacketResult
#function_name: build_review_packet

from pydantic import BaseModel, Field
from lemma_sdk import FunctionContext, Pod


class BuildReviewPacketInput(BaseModel):
    settlement_id: str = Field(description="The draft settlement to review.")
    review_request_id: str = Field(description="The open review request that started this run.")


class ReviewRequestRow(BaseModel):
    id: str
    settlement_id: str
    status: str
    reason: str | None = None
    requested_by: str | None = None
    requested_at: str | None = None


class SettlementRow(BaseModel):
    id: str
    show_id: str
    status: str
    ticket_revenue_cents: int
    fees_cents: int
    net_box_office_cents: int
    recoupable_total_cents: int
    recoup_cap_cents: int
    recouped_cents: int
    over_cap_cents: int
    pool_cents: int
    deal_type: str
    guarantee_cents: int
    percentage_bps: int
    calculated_payout_cents: int
    prepared_at: str | None = None
    calculation_version: str | None = None


class ShowRow(BaseModel):
    id: str
    artist: str
    billing: str | None = None
    show_date: str
    room: str | None = None
    deal_type: str
    guarantee_cents: int
    percentage_bps: int
    expense_cap_cents: int
    status: str
    external_ref: str | None = None


class TicketSaleRow(BaseModel):
    channel: str
    paid_quantity: int
    face_value_cents: int
    fees_cents: int
    comps: int
    source_ref: str | None = None
    recorded_at: str | None = None


class ExpenseRow(BaseModel):
    vendor: str
    category: str
    amount_cents: int
    recoupable: bool
    receipt_ref: str | None = None
    incurred_on: str | None = None
    note: str | None = None


class SettingsRow(BaseModel):
    venue_name: str | None = None
    room_name: str | None = None
    comp_allowance: int
    receipt_threshold_cents: int
    receipt_threshold: str
    currency: str


class EventRow(BaseModel):
    kind: str
    actor: str | None = None
    detail: str | None = None
    occurred_at: str


class PriorPaidRow(BaseModel):
    id: str
    status: str
    approved_payout_cents: int | None = None
    paid_at: str | None = None
    payment_ref: str | None = None


class DerivedDisplay(BaseModel):
    ticket_revenue: str
    fees: str
    net_box_office: str
    recoupable_total: str
    recoup_cap: str
    recouped: str
    over_cap: str
    pool: str
    calculated_payout: str


class DerivedMath(BaseModel):
    ticket_revenue_cents: int
    fees_cents: int
    fees_share_bps: int
    net_box_office_cents: int
    recoupable_total_cents: int
    recoup_cap_cents: int
    recouped_cents: int
    over_cap_cents: int
    pool_cents: int
    calculated_payout_cents: int
    display: DerivedDisplay


class ReviewPacket(BaseModel):
    review_request: ReviewRequestRow
    settlement: SettlementRow
    show: ShowRow
    ticket_sales: list[TicketSaleRow]
    expenses: list[ExpenseRow]
    settings: SettingsRow
    events: list[EventRow]
    prior_paid: list[PriorPaidRow]
    derived: DerivedMath


class BuildReviewPacketResult(BaseModel):
    packet: ReviewPacket


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return bool(value)


def _percent_of(amount_cents: int, basis_points: int) -> int:
    if amount_cents < 0 or basis_points < 0:
        raise ValueError("percent_of expects non-negative integers")
    return (amount_cents * basis_points + 5_000) // 10_000


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _derive(show: dict, sales: list[dict], expenses: list[dict]) -> DerivedMath:
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

    fees_share_bps = (
        (fees * 10_000 + ticket_revenue // 2) // ticket_revenue if ticket_revenue else 0
    )
    return DerivedMath(
        ticket_revenue_cents=ticket_revenue,
        fees_cents=fees,
        fees_share_bps=fees_share_bps,
        net_box_office_cents=net_box_office,
        recoupable_total_cents=recoupable_total,
        recoup_cap_cents=cap,
        recouped_cents=recouped,
        over_cap_cents=over_cap,
        pool_cents=pool,
        calculated_payout_cents=payout,
        display=DerivedDisplay(
            ticket_revenue=_money(ticket_revenue),
            fees=_money(fees),
            net_box_office=_money(net_box_office),
            recoupable_total=_money(recoupable_total),
            recoup_cap=_money(cap),
            recouped=_money(recouped),
            over_cap=_money(over_cap),
            pool=_money(pool),
            calculated_payout=_money(payout),
        ),
    )


async def build_review_packet(
    ctx: FunctionContext, data: BuildReviewPacketInput
) -> BuildReviewPacketResult:
    pod = Pod.from_env()

    request = pod.table("review_requests").get(data.review_request_id)
    if str(request.get("settlement_id") or "") != data.settlement_id:
        raise ValueError("The review request does not point at this settlement.")

    settlement = pod.table("settlements").get(data.settlement_id)
    show = pod.table("shows").get(str(settlement.get("show_id") or ""))
    if not show:
        raise ValueError("The settlement has no show row.")

    settings_rows = pod.records.list_all("settings", page_size=10)
    if not settings_rows:
        raise ValueError("The venue settings row is missing.")
    settings = settings_rows[0]

    sales = pod.records.list_all("ticket_sales", page_size=1_000)
    sales = [row for row in sales if str(row.get("show_id") or "") == str(show.get("id"))]

    expenses = pod.records.list_all("expenses", page_size=1_000)
    expenses = [
        row for row in expenses if str(row.get("show_id") or "") == str(show.get("id"))
    ]

    events = pod.records.list_all("settlement_events", page_size=1_000)
    events = [
        row
        for row in events
        if str(row.get("settlement_id") or "") == data.settlement_id
    ]
    events.sort(key=lambda row: str(row.get("occurred_at") or ""))

    settlements = pod.records.list_all("settlements", page_size=1_000)
    prior_paid = [
        row
        for row in settlements
        if str(row.get("show_id") or "") == str(show.get("id"))
        and str(row.get("status") or "") == "paid"
        and str(row.get("id") or "") != data.settlement_id
    ]

    packet = ReviewPacket(
        review_request=ReviewRequestRow(
            id=str(request.get("id") or ""),
            settlement_id=str(request.get("settlement_id") or ""),
            status=str(request.get("status") or ""),
            reason=request.get("reason"),
            requested_by=request.get("requested_by"),
            requested_at=request.get("requested_at"),
        ),
        settlement=SettlementRow(
            id=str(settlement.get("id") or ""),
            show_id=str(settlement.get("show_id") or ""),
            status=str(settlement.get("status") or ""),
            ticket_revenue_cents=int(settlement.get("ticket_revenue_cents") or 0),
            fees_cents=int(settlement.get("fees_cents") or 0),
            net_box_office_cents=int(settlement.get("net_box_office_cents") or 0),
            recoupable_total_cents=int(settlement.get("recoupable_total_cents") or 0),
            recoup_cap_cents=int(settlement.get("recoup_cap_cents") or 0),
            recouped_cents=int(settlement.get("recouped_cents") or 0),
            over_cap_cents=int(settlement.get("over_cap_cents") or 0),
            pool_cents=int(settlement.get("pool_cents") or 0),
            deal_type=str(settlement.get("deal_type") or ""),
            guarantee_cents=int(settlement.get("guarantee_cents") or 0),
            percentage_bps=int(settlement.get("percentage_bps") or 0),
            calculated_payout_cents=int(settlement.get("calculated_payout_cents") or 0),
            prepared_at=settlement.get("prepared_at"),
            calculation_version=settlement.get("calculation_version"),
        ),
        show=ShowRow(
            id=str(show.get("id") or ""),
            artist=str(show.get("artist") or ""),
            billing=show.get("billing"),
            show_date=str(show.get("show_date") or ""),
            room=show.get("room"),
            deal_type=str(show.get("deal_type") or ""),
            guarantee_cents=int(show.get("guarantee_cents") or 0),
            percentage_bps=int(show.get("percentage_bps") or 0),
            expense_cap_cents=int(show.get("expense_cap_cents") or 0),
            status=str(show.get("status") or ""),
            external_ref=show.get("external_ref"),
        ),
        ticket_sales=[
            TicketSaleRow(
                channel=str(row.get("channel") or ""),
                paid_quantity=int(row.get("paid_quantity") or 0),
                face_value_cents=int(row.get("face_value_cents") or 0),
                fees_cents=int(row.get("fees_cents") or 0),
                comps=int(row.get("comps") or 0),
                source_ref=row.get("source_ref"),
                recorded_at=row.get("recorded_at"),
            )
            for row in sales
        ],
        expenses=[
            ExpenseRow(
                vendor=str(row.get("vendor") or ""),
                category=str(row.get("category") or ""),
                amount_cents=int(row.get("amount_cents") or 0),
                recoupable=_truthy(row.get("recoupable")),
                receipt_ref=row.get("receipt_ref"),
                incurred_on=row.get("incurred_on"),
                note=row.get("note"),
            )
            for row in expenses
        ],
        settings=SettingsRow(
            venue_name=settings.get("venue_name"),
            room_name=settings.get("room_name"),
            comp_allowance=int(settings.get("comp_allowance") or 0),
            receipt_threshold_cents=int(settings.get("receipt_threshold_cents") or 0),
            receipt_threshold=_money(int(settings.get("receipt_threshold_cents") or 0)),
            currency=str(settings.get("currency") or "USD"),
        ),
        events=[
            EventRow(
                kind=str(row.get("kind") or ""),
                actor=row.get("actor"),
                detail=row.get("detail"),
                occurred_at=str(row.get("occurred_at") or ""),
            )
            for row in events
        ],
        prior_paid=[
            PriorPaidRow(
                id=str(row.get("id") or ""),
                status=str(row.get("status") or ""),
                approved_payout_cents=row.get("approved_payout_cents"),
                paid_at=row.get("paid_at"),
                payment_ref=row.get("payment_ref"),
            )
            for row in prior_paid
        ],
        derived=_derive(show, sales, expenses),
    )
    return BuildReviewPacketResult(packet=packet)
