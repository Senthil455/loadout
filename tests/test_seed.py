from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from settlement_math import Expense, Sale, Show, compute

ROOT = Path(__file__).resolve().parent.parent
TABLES = ROOT / "tables"

EXPECTED_PAYOUTS = {
    "Nia Calder": 120_000,
    "Harbor Lights": 199_150,
    "The Quiet Hours": 275_275,
    "Otis Bell": 85_000,
    "Saltwater Choir": 283_125,
    "Mira and the Tides": 190_890,
    "Low Ceiling": 95_000,
    "Fable & Stone": 201_890,
    "Rookery": 293_100,
    "June Almeida": 130_000,
}
CHECK_IDS = {
    "packet_integrity",
    "channels",
    "fees",
    "receipts",
    "recoup_cap",
    "comps",
    "deal_math",
    "payout_floor",
    "prior_payment",
    "reopen_context",
}


def rows(table: str) -> list[dict[str, str]]:
    with (TABLES / table / "data.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def seed() -> dict[str, list[dict[str, str]]]:
    return {
        "shows": rows("shows"),
        "ticket_sales": rows("ticket_sales"),
        "expenses": rows("expenses"),
        "settlements": rows("settlements"),
        "settlement_events": rows("settlement_events"),
        "review_requests": rows("review_requests"),
        "settings": rows("settings"),
    }


def computed_for(seed: dict[str, list[dict[str, str]]], show: dict[str, str]):
    sales = [row for row in seed["ticket_sales"] if row["show_id"] == show["id"]]
    expenses = [row for row in seed["expenses"] if row["show_id"] == show["id"]]
    return compute(
        Show(
            id=show["id"],
            show_date=show["show_date"],
            artist=show["artist"],
            deal_type=show["deal_type"],
            guarantee_cents=int(show["guarantee_cents"]),
            percentage_bps=int(show["percentage_bps"]),
            expense_cap_cents=int(show["expense_cap_cents"]),
        ),
        [
            Sale(
                paid_quantity=int(row["paid_quantity"]),
                face_value_cents=int(row["face_value_cents"]),
                fees_cents=int(row["fees_cents"]),
                comps=int(row["comps"]),
            )
            for row in sales
        ],
        [
            Expense(
                amount_cents=int(row["amount_cents"]),
                recoupable=row["recoupable"].lower() == "true",
            )
            for row in expenses
        ],
    )


def test_ten_played_shows_and_four_waiting(seed) -> None:
    shows = seed["shows"]
    assert len(shows) == 10
    assert all(show["status"] == "played" for show in shows)
    settled = {row["show_id"] for row in seed["settlements"]}
    waiting = [show for show in shows if show["id"] not in settled]
    assert {show["artist"] for show in waiting} == {
        "Low Ceiling",
        "Fable & Stone",
        "Rookery",
        "June Almeida",
    }


def test_every_demo_payout_matches_the_formula(seed) -> None:
    for show in seed["shows"]:
        result = computed_for(seed, show)
        assert result.calculated_payout_cents == EXPECTED_PAYOUTS[show["artist"]], show["artist"]


def test_historical_settlements_match_their_source_rows(seed) -> None:
    shows = {show["id"]: show for show in seed["shows"]}
    for settlement in seed["settlements"]:
        result = computed_for(seed, shows[settlement["show_id"]])
        assert int(settlement["ticket_revenue_cents"]) == result.ticket_revenue_cents
        assert int(settlement["fees_cents"]) == result.fees_cents
        assert int(settlement["recoupable_total_cents"]) == result.recoupable_total_cents
        assert int(settlement["recouped_cents"]) == result.recouped_cents
        assert int(settlement["over_cap_cents"]) == result.over_cap_cents
        assert int(settlement["pool_cents"]) == result.pool_cents
        assert int(settlement["calculated_payout_cents"]) == result.calculated_payout_cents


def test_paid_and_held_rows_carry_the_right_fields(seed) -> None:
    paid = [row for row in seed["settlements"] if row["status"] == "paid"]
    held = [row for row in seed["settlements"] if row["status"] == "held"]
    assert len(paid) == 5
    assert len(held) == 1
    for row in paid:
        assert row["approved_at"]
        assert row["approved_by"] == "manager@lanternroom.test"
        assert row["paid_at"]
        assert row["payment_ref"].startswith("ACH-")
    for row in held:
        assert not row["approved_at"]
        assert not row["approved_by"]
        assert not row["paid_at"]
        assert row["payment_ref"] == ""
        assert row["review_note"]


def test_every_seeded_review_uses_all_ten_check_ids(seed) -> None:
    for row in seed["settlements"]:
        review = json.loads(row["agent_review"])
        ids = [finding["check"] for finding in review["findings"]]
        assert len(ids) == 10
        assert set(ids) == CHECK_IDS
        assert len(set(ids)) == 10
        rank = {"block": 0, "watch": 1, "pass": 2}
        assert [rank[finding["status"]] for finding in review["findings"]] == sorted(
            rank[finding["status"]] for finding in review["findings"]
        )


def test_held_review_names_the_block_and_the_watches(seed) -> None:
    held = next(row for row in seed["settlements"] if row["status"] == "held")
    review = json.loads(held["agent_review"])
    by_id = {finding["check"]: finding for finding in review["findings"]}
    assert review["recommendation"] == "hold"
    assert by_id["receipts"]["status"] == "block"
    assert "Clearwater Backline" in by_id["receipts"]["detail"]
    assert "1,800.00" in by_id["receipts"]["detail"]
    assert by_id["recoup_cap"]["status"] == "watch"
    assert by_id["comps"]["status"] == "watch"
    assert "18 comps" in by_id["comps"]["detail"]


def test_reviews_with_one_watch_still_recommend_approval(seed) -> None:
    saltwater = next(
        row for row in seed["settlements"]
        if json.loads(row["agent_review"])["headline"].startswith("Clear to pay $2,831.25")
    )
    review = json.loads(saltwater["agent_review"])
    assert review["recommendation"] == "approve"
    assert sum(1 for finding in review["findings"] if finding["status"] == "watch") == 1


def test_missing_receipts_are_the_two_intended_ones(seed) -> None:
    missing = sorted(
        (
            show["artist"],
            expense["vendor"],
            int(expense["amount_cents"]),
        )
        for show in seed["shows"]
        for expense in seed["expenses"]
        if expense["show_id"] == show["id"]
        and expense["recoupable"].lower() == "true"
        and int(expense["amount_cents"]) >= 25_000
        and not expense["receipt_ref"].strip()
    )
    assert missing == [
        ("June Almeida", "Northline Audio", 125_000),
        ("Mira and the Tides", "Clearwater Backline", 180_000),
    ]


def test_first_cycle_starts_from_a_clean_request_table(seed) -> None:
    assert len(seed["review_requests"]) == 6
    assert all(row["status"] == "closed" for row in seed["review_requests"])
    assert seed["settings"][0]["approval_member_id"] == ""


def test_events_cover_every_state_change(seed) -> None:
    events = seed["settlement_events"]
    for settlement in seed["settlements"]:
        kinds = [event["kind"] for event in events if event["settlement_id"] == settlement["id"]]
        assert "prepared" in kinds
        assert "review_ready" in kinds
        if settlement["status"] == "paid":
            assert "approved" in kinds
            assert "paid" in kinds
        if settlement["status"] == "held":
            assert "held" in kinds
