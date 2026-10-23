from __future__ import annotations

import asyncio

import pytest

from fakes import (
    FakeContext,
    FakePod,
    load_function,
    request_row,
    seeded_pod,
    settlement_row,
)


@pytest.fixture(autouse=True)
def clean_pod():
    FakePod.current = None
    yield
    FakePod.current = None


def use(pod: FakePod) -> None:
    FakePod.current = pod


def test_prepare_creates_four_packets_and_is_idempotent() -> None:
    module = load_function("prepare_settlements")
    pod = seeded_pod()
    use(pod)

    result = asyncio.run(module.prepare_settlements(FakeContext(), module.PrepareSettlementsInput(as_of="2026-10-23")))
    assert result.prepared == 4
    assert result.skipped == 6
    assert result.recovered == 0
    assert len(pod.table("settlements").rows) == 10
    assert len(pod.table("review_requests").rows) == 10
    assert len([row for row in pod.table("settlement_events").rows if row["kind"] == "prepared"]) == 10

    by_artist = {
        show["artist"]: row
        for row in pod.table("settlements").rows
        for show in pod.table("shows").rows
        if show["id"] == row["show_id"]
    }
    assert by_artist["Fable & Stone"]["calculated_payout_cents"] == 201_890
    assert by_artist["Rookery"]["calculated_payout_cents"] == 293_100
    assert by_artist["June Almeida"]["calculated_payout_cents"] == 130_000
    assert by_artist["Low Ceiling"]["calculated_payout_cents"] == 95_000
    for artist in ("Fable & Stone", "Rookery", "June Almeida", "Low Ceiling"):
        assert by_artist[artist]["status"] == "draft"

    second = asyncio.run(module.prepare_settlements(FakeContext(), module.PrepareSettlementsInput(as_of="2026-10-23")))
    assert second.prepared == 0
    assert second.skipped == 10
    assert len(pod.table("settlements").rows) == 10


def test_prepare_respects_the_cutoff_date() -> None:
    module = load_function("prepare_settlements")
    pod = seeded_pod()
    use(pod)

    result = asyncio.run(module.prepare_settlements(FakeContext(), module.PrepareSettlementsInput(as_of="2026-10-09")))
    assert result.prepared == 1
    created = pod.table("settlements").rows[-1]
    show = next(row for row in pod.table("shows").rows if row["id"] == created["show_id"])
    assert show["artist"] == "Low Ceiling"


def test_prepare_recovers_a_draft_without_a_request() -> None:
    module = load_function("prepare_settlements")
    pod = seeded_pod()
    use(pod)
    first = pod.table("settlements").rows[0]
    first["status"] = "draft"
    pod.tables["review_requests"].rows = [
        row for row in pod.table("review_requests").rows if row["settlement_id"] != first["id"]
    ]

    result = asyncio.run(module.prepare_settlements(FakeContext(), module.PrepareSettlementsInput(as_of="2026-10-23")))
    assert result.recovered == 1
    assert any(
        row["settlement_id"] == first["id"] and row["status"] == "open"
        for row in pod.table("review_requests").rows
    )


def review_args(**overrides):
    values = {
        "review_request_id": "request-1",
        "settlement_id": "settlement-1",
        "headline": "Clear to pay $532.00",
        "recommendation": "approve",
        "findings": [
            {"check": "packet_integrity", "status": "pass", "detail": "All three records agree."},
            {"check": "receipts", "status": "pass", "detail": "Every receipt is present."},
        ],
        "review_note": "The packet ties out.",
        "confidence": 0.93,
    }
    values.update(overrides)
    return values


def test_attach_review_stores_findings_and_returns_the_approver() -> None:
    module = load_function("attach_review")
    pod = FakePod({
        "settlements": [settlement_row(status="draft")],
        "review_requests": [request_row()],
        "shows": [{"id": "show-1", "artist": "Test Artist", "show_date": "2026-09-30"}],
        "settings": [{"id": "settings-1", "approval_member_id": "member-1"}],
        "settlement_events": [],
    })
    use(pod)

    result = asyncio.run(module.attach_review(FakeContext(), module.AttachReviewInput(**review_args())))
    assert result.can_review is True
    assert result.approval_member_id == "member-1"
    assert result.payout_cents == 53_200
    settlement = pod.table("settlements").get("settlement-1")
    assert settlement["status"] == "awaiting_approval"
    assert settlement["agent_review"]["recommendation"] == "approve"
    assert len(settlement["agent_review"]["findings"]) == 2
    assert pod.table("settlement_events").rows[-1]["kind"] == "review_ready"


def test_attach_review_refuses_a_closed_request() -> None:
    module = load_function("attach_review")
    pod = FakePod({
        "settlements": [settlement_row(status="draft")],
        "review_requests": [request_row(status="closed")],
        "shows": [{"id": "show-1", "artist": "Test Artist", "show_date": "2026-09-30"}],
        "settings": [{"id": "settings-1", "approval_member_id": ""}],
        "settlement_events": [],
    })
    use(pod)

    result = asyncio.run(module.attach_review(FakeContext(), module.AttachReviewInput(**review_args())))
    assert result.can_review is False
    assert result.approval_member_id == ""
    assert pod.table("settlements").get("settlement-1")["status"] == "draft"


def test_attach_review_does_not_overwrite_a_hold() -> None:
    module = load_function("attach_review")
    pod = FakePod({
        "settlements": [settlement_row(status="held")],
        "review_requests": [request_row()],
        "shows": [{"id": "show-1", "artist": "Test Artist", "show_date": "2026-09-30"}],
        "settings": [{"id": "settings-1", "approval_member_id": ""}],
        "settlement_events": [],
    })
    use(pod)

    result = asyncio.run(module.attach_review(FakeContext(), module.AttachReviewInput(**review_args())))
    assert result.can_review is False
    assert result.settlement_status == "held"
    assert pod.table("settlements").get("settlement-1")["status"] == "held"
    assert pod.table("review_requests").get("request-1")["status"] == "closed"


def test_record_review_approves_with_the_submitter_email() -> None:
    module = load_function("record_review")
    pod = FakePod({
        "settlements": [settlement_row()],
        "review_requests": [request_row()],
        "settlement_events": [],
    })
    use(pod)

    result = asyncio.run(module.record_review(FakeContext(email="owner@example.com"), module.RecordReviewInput(
        review_request_id="request-1",
        settlement_id="settlement-1",
        approved=True,
        payout_cents=53_200,
        review_note="Checked the receipt.",
        decided_by="manager@lanternroom.test",
    )))
    assert result.status == "approved"
    assert result.approved_payout_cents == 53_200
    settlement = pod.table("settlements").get("settlement-1")
    assert settlement["approved_by"] == "manager@lanternroom.test"
    assert settlement["approved_at"]
    assert settlement["review_note"] == "Checked the receipt."
    assert pod.table("review_requests").get("request-1")["status"] == "closed"
    event = pod.table("settlement_events").rows[-1]
    assert event["kind"] == "approved"
    assert "$532.00" in event["detail"]


def test_record_review_falls_back_to_the_run_identity() -> None:
    module = load_function("record_review")
    pod = FakePod({
        "settlements": [settlement_row()],
        "review_requests": [request_row()],
        "settlement_events": [],
    })
    use(pod)

    asyncio.run(module.record_review(FakeContext(email="owner@example.com"), module.RecordReviewInput(
        review_request_id="request-1",
        settlement_id="settlement-1",
        approved=True,
        payout_cents=53_200,
    )))
    assert pod.table("settlements").get("settlement-1")["approved_by"] == "owner@example.com"


def test_record_review_requires_a_note_for_a_changed_amount() -> None:
    module = load_function("record_review")
    pod = FakePod({
        "settlements": [settlement_row()],
        "review_requests": [request_row()],
        "settlement_events": [],
    })
    use(pod)

    with pytest.raises(ValueError, match="needs a note"):
        asyncio.run(module.record_review(FakeContext(), module.RecordReviewInput(
            review_request_id="request-1",
            settlement_id="settlement-1",
            approved=True,
            payout_cents=50_000,
        )))
    assert pod.table("settlements").get("settlement-1")["status"] == "awaiting_approval"

    result = asyncio.run(module.record_review(FakeContext(), module.RecordReviewInput(
        review_request_id="request-1",
        settlement_id="settlement-1",
        approved=True,
        payout_cents=50_000,
        review_note="The artist agreed to waive the balance.",
    )))
    assert result.status == "approved"
    assert result.approved_payout_cents == 50_000


def test_record_review_holds_and_clears_the_decision() -> None:
    module = load_function("record_review")
    pod = FakePod({
        "settlements": [settlement_row(status="awaiting_approval", approved_payout_cents=None)],
        "review_requests": [request_row()],
        "settlement_events": [],
    })
    use(pod)

    result = asyncio.run(module.record_review(FakeContext(), module.RecordReviewInput(
        review_request_id="request-1",
        settlement_id="settlement-1",
        approved=False,
        review_note="Waiting on the backline invoice.",
    )))
    assert result.status == "held"
    assert result.approved_payout_cents == 0
    settlement = pod.table("settlements").get("settlement-1")
    assert settlement["approved_payout_cents"] is None
    assert settlement["approved_by"] is None
    assert settlement["approved_at"] is None
    assert settlement["review_note"] == "Waiting on the backline invoice."
    assert pod.table("settlement_events").rows[-1]["kind"] == "held"


def test_record_review_is_idempotent_after_a_decision() -> None:
    module = load_function("record_review")
    pod = FakePod({
        "settlements": [settlement_row(status="approved", approved_payout_cents=53_200)],
        "review_requests": [request_row()],
        "settlement_events": [],
    })
    use(pod)

    result = asyncio.run(module.record_review(FakeContext(), module.RecordReviewInput(
        review_request_id="request-1",
        settlement_id="settlement-1",
        approved=True,
        payout_cents=53_200,
    )))
    assert result.already_recorded is True
    assert pod.table("review_requests").get("request-1")["status"] == "closed"
    assert pod.table("settlement_events").rows == []


def test_mark_paid_closes_an_approved_settlement() -> None:
    module = load_function("mark_paid")
    pod = FakePod({
        "settlements": [settlement_row(status="approved", approved_payout_cents=53_200)],
        "settlement_events": [],
    })
    use(pod)

    result = asyncio.run(module.mark_paid(FakeContext(), module.MarkPaidInput(
        settlement_id="settlement-1",
        payment_ref="ACH-261023-01",
    )))
    assert result.status == "paid"
    assert result.paid_cents == 53_200
    settlement = pod.table("settlements").get("settlement-1")
    assert settlement["payment_ref"] == "ACH-261023-01"
    assert settlement["paid_at"]
    assert pod.table("settlement_events").rows[-1]["kind"] == "paid"

    again = asyncio.run(module.mark_paid(FakeContext(), module.MarkPaidInput(
        settlement_id="settlement-1",
        payment_ref="ACH-261023-02",
    )))
    assert again.already_recorded is True
    assert again.payment_ref == "ACH-261023-01"


def test_mark_paid_refuses_anything_not_approved() -> None:
    module = load_function("mark_paid")
    pod = FakePod({
        "settlements": [settlement_row(status="awaiting_approval")],
        "settlement_events": [],
    })
    use(pod)
    with pytest.raises(ValueError, match="only an approved settlement"):
        asyncio.run(module.mark_paid(FakeContext(), module.MarkPaidInput(
            settlement_id="settlement-1",
            payment_ref="ACH-261023-01",
        )))


def test_reopen_creates_a_fresh_request_without_recomputing() -> None:
    module = load_function("reopen_settlement")
    settlement = settlement_row(status="held", review_note="Missing receipt.")
    pod = FakePod({
        "settlements": [settlement],
        "review_requests": [request_row(status="closed")],
        "settlement_events": [],
    })
    use(pod)

    result = asyncio.run(module.reopen_settlement(FakeContext(), module.ReopenSettlementInput(
        settlement_id="settlement-1",
        reason="The backline invoice arrived.",
    )))
    assert result.can_reopen is True
    updated = pod.table("settlements").get("settlement-1")
    assert updated["status"] == "draft"
    assert updated["approved_payout_cents"] is None
    assert updated["approved_by"] is None
    assert updated["calculated_payout_cents"] == 53_200
    new_request = pod.table("review_requests").rows[-1]
    assert new_request["status"] == "open"
    assert new_request["reason"] == "The backline invoice arrived."
    assert pod.table("settlement_events").rows[-1]["kind"] == "reopened"


def test_reopen_refuses_a_paid_settlement() -> None:
    module = load_function("reopen_settlement")
    pod = FakePod({
        "settlements": [settlement_row(status="paid")],
        "review_requests": [],
        "settlement_events": [],
    })
    use(pod)
    with pytest.raises(ValueError, match="cannot be reopened"):
        asyncio.run(module.reopen_settlement(FakeContext(), module.ReopenSettlementInput(
            settlement_id="settlement-1",
            reason="Trying to change a closed settlement.",
        )))


def test_reopen_refuses_when_a_request_is_already_open() -> None:
    module = load_function("reopen_settlement")
    pod = FakePod({
        "settlements": [settlement_row(status="held")],
        "review_requests": [request_row()],
        "settlement_events": [],
    })
    use(pod)
    result = asyncio.run(module.reopen_settlement(FakeContext(), module.ReopenSettlementInput(
        settlement_id="settlement-1",
        reason="A second review.",
    )))
    assert result.can_reopen is False
    assert pod.table("settlements").get("settlement-1")["status"] == "held"


def packet_pod(**settlement_overrides):
    return FakePod({
        "review_requests": [request_row()],
        "settlements": [settlement_row(status="draft", **settlement_overrides)],
        "shows": [{
            "id": "show-1",
            "artist": "Packet Artist",
            "billing": "Packet Artist with Guest",
            "show_date": "2026-10-17",
            "room": "Main Room",
            "deal_type": "PERCENTAGE",
            "guarantee_cents": "0",
            "percentage_bps": "7000",
            "expense_cap_cents": "50000",
            "status": "played",
            "external_ref": "SHOW-1",
        }],
        "ticket_sales": [
            {
                "show_id": "show-1",
                "channel": "online",
                "paid_quantity": "100",
                "face_value_cents": "1000",
                "fees_cents": "3000",
                "comps": "4",
                "source_ref": "WEB-1",
                "recorded_at": "2026-10-18T09:00:00Z",
            },
            {
                "show_id": "show-1",
                "channel": "door",
                "paid_quantity": "10",
                "face_value_cents": "1000",
                "fees_cents": "1000",
                "comps": "2",
                "source_ref": "DOOR-1",
                "recorded_at": "2026-10-18T09:05:00Z",
            },
        ],
        "expenses": [
            {
                "show_id": "show-1",
                "vendor": "Backline",
                "category": "backline",
                "amount_cents": "20000",
                "recoupable": "true",
                "receipt_ref": "REC-1",
                "incurred_on": "2026-10-17",
                "note": "",
            },
            {
                "show_id": "show-1",
                "vendor": "Coffee",
                "category": "catering",
                "amount_cents": "5000",
                "recoupable": "false",
                "receipt_ref": "",
                "incurred_on": "2026-10-17",
                "note": "House expense",
            },
        ],
        "settings": [{
            "venue_name": "The Lantern Room",
            "room_name": "Main Room",
            "comp_allowance": "12",
            "receipt_threshold_cents": "25000",
            "currency": "USD",
        }],
        "settlement_events": [{
            "settlement_id": "settlement-1",
            "kind": "prepared",
            "actor": "prepare_settlements",
            "detail": "Prepared.",
            "occurred_at": "2026-10-18T09:10:00Z",
        }],
    })


def test_build_review_packet_derives_the_math_from_raw_rows() -> None:
    module = load_function("build_review_packet")
    use(packet_pod())

    result = asyncio.run(module.build_review_packet(
        FakeContext(),
        module.BuildReviewPacketInput(
            settlement_id="settlement-1",
            review_request_id="request-1",
        ),
    ))
    packet = result.packet

    assert packet.review_request.id == "request-1"
    assert packet.show.artist == "Packet Artist"
    assert len(packet.ticket_sales) == 2
    assert packet.derived.ticket_revenue_cents == 110_000
    assert packet.derived.fees_cents == 4_000
    assert packet.derived.fees_share_bps == 364
    assert packet.derived.recoupable_total_cents == 20_000
    assert packet.derived.recouped_cents == 20_000
    assert packet.derived.pool_cents == 86_000
    assert packet.derived.calculated_payout_cents == 60_200
    assert packet.derived.display.pool == "$860.00"
    assert packet.expenses[1].recoupable is False
    assert packet.settings.receipt_threshold == "$250.00"
    assert packet.events[0].kind == "prepared"


def test_build_review_packet_refuses_a_request_for_another_settlement() -> None:
    module = load_function("build_review_packet")
    pod = packet_pod()
    pod.table("review_requests").rows[0]["settlement_id"] = "other-settlement"
    use(pod)

    with pytest.raises(ValueError, match="does not point"):
        asyncio.run(module.build_review_packet(
            FakeContext(),
            module.BuildReviewPacketInput(
                settlement_id="settlement-1",
                review_request_id="request-1",
            ),
        ))
