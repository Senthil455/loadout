from __future__ import annotations

import pytest

from settlement_math import Expense, Sale, Show, compute, percent_of


def show(deal_type: str, guarantee: int = 0, bps: int = 0, cap: int = 0) -> Show:
    return Show(
        id="show-1",
        show_date="2026-10-01",
        artist="Test Artist",
        deal_type=deal_type,
        guarantee_cents=guarantee,
        percentage_bps=bps,
        expense_cap_cents=cap,
    )


def test_flat_deal_pays_the_guarantee_even_when_the_pool_is_larger() -> None:
    result = compute(
        show("FLAT", guarantee=120_000, cap=200_000),
        [Sale(paid_quantity=100, face_value_cents=3_000, fees_cents=12_000, comps=2)],
        [Expense(amount_cents=50_000, recoupable=True)],
    )
    assert result.ticket_revenue_cents == 300_000
    assert result.net_box_office_cents == 288_000
    assert result.pool_cents == 238_000
    assert result.calculated_payout_cents == 120_000


def test_percentage_deal_pays_a_share_of_the_pool() -> None:
    result = compute(
        show("PERCENTAGE", bps=7_000, cap=250_000),
        [
            Sale(paid_quantity=142, face_value_cents=2_600, fees_cents=14_800, comps=5),
            Sale(paid_quantity=41, face_value_cents=3_000, fees_cents=4_900, comps=3),
        ],
        [Expense(amount_cents=188_000, recoupable=True)],
    )
    assert result.ticket_revenue_cents == 492_200
    assert result.pool_cents == 284_500
    assert result.calculated_payout_cents == 199_150


def test_vs_deal_takes_the_greater_side() -> None:
    percentage_wins = compute(
        show("VS", guarantee=90_000, bps=6_500, cap=280_000),
        [
            Sale(paid_quantity=160, face_value_cents=3_000, fees_cents=19_200, comps=7),
            Sale(paid_quantity=52, face_value_cents=3_400, fees_cents=7_100, comps=3),
        ],
        [Expense(amount_cents=207_000, recoupable=True)],
    )
    assert percentage_wins.pool_cents == 423_500
    assert percentage_wins.calculated_payout_cents == 275_275

    guarantee_wins = compute(
        show("VS", guarantee=400_000, bps=1_000, cap=100_000),
        [Sale(paid_quantity=10, face_value_cents=3_000, fees_cents=0, comps=0)],
        [],
    )
    assert guarantee_wins.calculated_payout_cents == 400_000


def test_recoup_cap_absorbs_the_overage() -> None:
    result = compute(
        show("PERCENTAGE", bps=7_000, cap=550_000),
        [
            Sale(paid_quantity=185, face_value_cents=3_400, fees_cents=25_200, comps=11),
            Sale(paid_quantity=60, face_value_cents=3_800, fees_cents=9_100, comps=7),
        ],
        [
            Expense(amount_cents=240_000, recoupable=True),
            Expense(amount_cents=180_000, recoupable=True),
            Expense(amount_cents=95_000, recoupable=True),
            Expense(amount_cents=60_000, recoupable=True),
            Expense(amount_cents=120_000, recoupable=False),
        ],
    )
    assert result.recoupable_total_cents == 575_000
    assert result.recouped_cents == 550_000
    assert result.over_cap_cents == 25_000
    assert result.pool_cents == 272_700
    assert result.calculated_payout_cents == 190_890


def test_pool_never_goes_below_zero() -> None:
    result = compute(
        show("PERCENTAGE", bps=7_000, cap=500_000),
        [Sale(paid_quantity=10, face_value_cents=1_000, fees_cents=0, comps=0)],
        [Expense(amount_cents=100_000, recoupable=True)],
    )
    assert result.pool_cents == 0
    assert result.calculated_payout_cents == 0


def test_half_up_rounding_on_an_exact_half_cent() -> None:
    assert percent_of(1, 5_000) == 1
    assert percent_of(3, 5_000) == 2
    assert percent_of(2_845_00, 7_000) == 199_150


def test_percent_of_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError):
        percent_of(-1, 7_000)
    with pytest.raises(ValueError):
        percent_of(100, -1)


def test_unknown_deal_type_is_refused() -> None:
    with pytest.raises(ValueError):
        compute(show("DOOR_SPLIT"), [], [])
