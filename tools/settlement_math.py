"""Deterministic settlement arithmetic for Loadout.

The pod function in `functions/prepare_settlements/code.py` carries its own copy
of these formulas because a bundle function is a single file. This module is the
one the seed builder and the verifier use, so the numbers in `data.csv` and the
numbers the pod computes come from the same rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Show:
    id: str
    show_date: str
    artist: str
    deal_type: str
    guarantee_cents: int
    percentage_bps: int
    expense_cap_cents: int


@dataclass(frozen=True)
class Sale:
    paid_quantity: int
    face_value_cents: int
    fees_cents: int
    comps: int


@dataclass(frozen=True)
class Expense:
    amount_cents: int
    recoupable: bool


@dataclass(frozen=True)
class Settlement:
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


def percent_of(amount_cents: int, basis_points: int) -> int:
    """A percentage of a cent amount, rounded half up to the nearest cent.

    Cents are integers all the way through. A float would turn a $1,991.50
    payout into 199149 on one machine and 199150 on another.
    """
    if amount_cents < 0 or basis_points < 0:
        raise ValueError("percent_of expects non-negative integers")
    return (amount_cents * basis_points + 5_000) // 10_000


def compute(
    show: Show,
    sales: Iterable[Sale],
    expenses: Iterable[Expense],
) -> Settlement:
    ticket_revenue = sum(s.paid_quantity * s.face_value_cents for s in sales)
    fees = sum(s.fees_cents for s in sales)
    net_box_office = ticket_revenue - fees

    recoupable_total = sum(e.amount_cents for e in expenses if e.recoupable)
    cap = show.expense_cap_cents
    recouped = min(recoupable_total, cap)
    over_cap = recoupable_total - recouped
    pool = max(0, net_box_office - recouped)

    share = percent_of(pool, show.percentage_bps)
    if show.deal_type == "FLAT":
        payout = show.guarantee_cents
    elif show.deal_type == "PERCENTAGE":
        payout = share
    elif show.deal_type == "VS":
        payout = max(show.guarantee_cents, share)
    else:
        raise ValueError(f"unknown deal type {show.deal_type!r}")

    return Settlement(
        ticket_revenue_cents=ticket_revenue,
        fees_cents=fees,
        net_box_office_cents=net_box_office,
        recoupable_total_cents=recoupable_total,
        recoup_cap_cents=cap,
        recouped_cents=recouped,
        over_cap_cents=over_cap,
        pool_cents=pool,
        deal_type=show.deal_type,
        guarantee_cents=show.guarantee_cents,
        percentage_bps=show.percentage_bps,
        calculated_payout_cents=payout,
    )


def sale_from_row(row: Mapping[str, object]) -> Sale:
    return Sale(
        paid_quantity=int(row["paid_quantity"]),
        face_value_cents=int(row["face_value_cents"]),
        fees_cents=int(row["fees_cents"]),
        comps=int(row["comps"]),
    )


def expense_from_row(row: Mapping[str, object]) -> Expense:
    recoupable = row["recoupable"]
    if isinstance(recoupable, str):
        recoupable = recoupable.strip().lower() in {"true", "1", "yes", "on"}
    return Expense(
        amount_cents=int(row["amount_cents"]),
        recoupable=bool(recoupable),
    )


def show_from_row(row: Mapping[str, object]) -> Show:
    return Show(
        id=str(row["id"]),
        show_date=str(row["show_date"]),
        artist=str(row["artist"]),
        deal_type=str(row["deal_type"]),
        guarantee_cents=int(row["guarantee_cents"]),
        percentage_bps=int(row["percentage_bps"]),
        expense_cap_cents=int(row["expense_cap_cents"]),
    )
