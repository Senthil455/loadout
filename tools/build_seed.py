"""Build the Loadout sample month.

Run from the repository root:

    python tools/build_seed.py

It rewrites `tables/<table>/data.csv`. The random-looking ids are UUIDv5 values
derived from stable keys, so a rebuild produces byte-identical files and the
settlement rows keep pointing at the same shows and ticket rows.

The six earlier shows are already settled or held, as if the venue moved onto
Loadout in the middle of the month. The four later shows have no settlement row;
the first live cycle prepares them.
"""

from __future__ import annotations

import csv
import json
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from settlement_math import Expense, Sale, Show, compute, percent_of  # noqa: E402

NS = uuid.UUID("6f9d3d8e-2b1a-5c47-9a6e-0d5f8c2b7a41")


def uid(kind: str, key: str) -> str:
    return str(uuid.uuid5(NS, f"{kind}:{key}"))


def usd(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def iso(day: str, hour: int = 9, minute: int = 0) -> str:
    return f"{day}T{hour:02d}:{minute:02d}:00Z"


def plus_day(day: str, days: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=days)).isoformat()


SHOWS = [
    {
        "key": "nia-calder-2026-09-18",
        "show_date": "2026-09-18",
        "artist": "Nia Calder",
        "billing": "Nia Calder with Halcyon",
        "deal_type": "FLAT",
        "guarantee_cents": 120_000,
        "percentage_bps": 0,
        "expense_cap_cents": 200_000,
        "notes": "Album release week. Sold out.",
    },
    {
        "key": "harbor-lights-2026-09-20",
        "show_date": "2026-09-20",
        "artist": "Harbor Lights",
        "billing": "Harbor Lights with Open Water",
        "deal_type": "PERCENTAGE",
        "guarantee_cents": 0,
        "percentage_bps": 7_000,
        "expense_cap_cents": 250_000,
        "notes": "Four-piece. Load-in at 4pm.",
    },
    {
        "key": "quiet-hours-2026-09-24",
        "show_date": "2026-09-24",
        "artist": "The Quiet Hours",
        "billing": "The Quiet Hours with Sable",
        "deal_type": "VS",
        "guarantee_cents": 90_000,
        "percentage_bps": 6_500,
        "expense_cap_cents": 280_000,
        "notes": "Sold out. Extra bar staff.",
    },
    {
        "key": "otis-bell-2026-09-27",
        "show_date": "2026-09-27",
        "artist": "Otis Bell",
        "billing": "Otis Bell",
        "deal_type": "FLAT",
        "guarantee_cents": 85_000,
        "percentage_bps": 0,
        "expense_cap_cents": 150_000,
        "notes": "Late add, reduced capacity.",
    },
    {
        "key": "saltwater-choir-2026-10-01",
        "show_date": "2026-10-01",
        "artist": "Saltwater Choir",
        "billing": "Saltwater Choir with the Ferrymen",
        "deal_type": "PERCENTAGE",
        "guarantee_cents": 0,
        "percentage_bps": 7_500,
        "expense_cap_cents": 260_000,
        "notes": "Benefit show. Full room.",
    },
    {
        "key": "mira-tides-2026-10-03",
        "show_date": "2026-10-03",
        "artist": "Mira and the Tides",
        "billing": "Mira and the Tides with Coral Room",
        "deal_type": "VS",
        "guarantee_cents": 140_000,
        "percentage_bps": 7_000,
        "expense_cap_cents": 550_000,
        "notes": "Tour kickoff. Backline rented.",
    },
    {
        "key": "low-ceiling-2026-10-08",
        "show_date": "2026-10-08",
        "artist": "Low Ceiling",
        "billing": "Low Ceiling with Paper Tiger",
        "deal_type": "FLAT",
        "guarantee_cents": 95_000,
        "percentage_bps": 0,
        "expense_cap_cents": 220_000,
        "notes": "Local opener added.",
    },
    {
        "key": "fable-stone-2026-10-10",
        "show_date": "2026-10-10",
        "artist": "Fable & Stone",
        "billing": "Fable & Stone with Juniper",
        "deal_type": "PERCENTAGE",
        "guarantee_cents": 0,
        "percentage_bps": 6_500,
        "expense_cap_cents": 240_000,
        "notes": "Guest list ran long.",
    },
    {
        "key": "rookery-2026-10-14",
        "show_date": "2026-10-14",
        "artist": "Rookery",
        "billing": "Rookery with Bellwether",
        "deal_type": "VS",
        "guarantee_cents": 110_000,
        "percentage_bps": 6_000,
        "expense_cap_cents": 300_000,
        "notes": "Second show added.",
    },
    {
        "key": "june-almeida-2026-10-17",
        "show_date": "2026-10-17",
        "artist": "June Almeida",
        "billing": "June Almeida with the Long Way Home",
        "deal_type": "FLAT",
        "guarantee_cents": 130_000,
        "percentage_bps": 0,
        "expense_cap_cents": 320_000,
        "notes": "Sold out. Production invoice pending.",
    },
]

# paid_quantity, face_value_cents, fees_cents, comps
SALES = {
    "nia-calder-2026-09-18": [(118, 2_800, 13_200, 4), (34, 3_200, 4_400, 2)],
    "harbor-lights-2026-09-20": [(142, 2_600, 14_800, 5), (41, 3_000, 4_900, 3)],
    "quiet-hours-2026-09-24": [(160, 3_000, 19_200, 7), (52, 3_400, 7_100, 3)],
    "otis-bell-2026-09-27": [(96, 2_400, 9_200, 4), (28, 2_800, 3_100, 2)],
    "saltwater-choir-2026-10-01": [(175, 2_700, 18_900, 9), (45, 3_100, 5_600, 5)],
    "mira-tides-2026-10-03": [(185, 3_400, 25_200, 11), (60, 3_800, 9_100, 7)],
    "low-ceiling-2026-10-08": [(130, 2_900, 15_100, 6), (33, 3_300, 4_400, 3)],
    "fable-stone-2026-10-10": [(155, 2_500, 15_500, 14), (39, 2_900, 4_500, 8)],
    "rookery-2026-10-14": [(168, 3_200, 21_500, 8), (47, 3_600, 6_800, 3)],
    "june-almeida-2026-10-17": [(190, 3_000, 22_800, 9), (55, 3_400, 7_500, 4)],
}

# vendor, category, amount_cents, recoupable, receipt_ref
EXPENSES = {
    "nia-calder-2026-09-18": [
        ("Northline Audio", "production", 80_000, True, "INV-0912"),
        ("Paper Lantern Print", "marketing", 35_000, True, "INV-0931"),
        ("Green Room Market", "hospitality", 28_000, True, "GR-441"),
        ("Nightshift Crew", "venue", 60_000, False, ""),
    ],
    "harbor-lights-2026-09-20": [
        ("Northline Audio", "production", 110_000, True, "INV-1004"),
        ("Paper Lantern Print", "marketing", 42_000, True, "INV-1011"),
        ("Green Room Market", "hospitality", 36_000, True, "GR-512"),
        ("Nightshift Crew", "venue", 70_000, False, ""),
    ],
    "quiet-hours-2026-09-24": [
        ("Northline Audio", "production", 130_000, True, "INV-1058"),
        ("Paper Lantern Print", "marketing", 45_000, True, "INV-1063"),
        ("Green Room Market", "hospitality", 32_000, True, "GR-587"),
        ("Nightshift Crew", "venue", 65_000, False, ""),
    ],
    "otis-bell-2026-09-27": [
        ("Northline Audio", "production", 70_000, True, "INV-1081"),
        ("Paper Lantern Print", "marketing", 30_000, True, "INV-1088"),
        ("Green Room Market", "hospitality", 22_000, True, "GR-604"),
        ("Nightshift Crew", "venue", 50_000, False, ""),
    ],
    "saltwater-choir-2026-10-01": [
        ("Northline Audio", "production", 120_000, True, "INV-1120"),
        ("Paper Lantern Print", "marketing", 50_000, True, "INV-1129"),
        ("Green Room Market", "hospitality", 40_000, True, "GR-651"),
        ("Nightshift Crew", "venue", 60_000, False, ""),
    ],
    "mira-tides-2026-10-03": [
        ("Northline Audio", "production", 240_000, True, "INV-1042"),
        ("Clearwater Backline", "production", 180_000, True, ""),
        ("Green Room Market", "hospitality", 95_000, True, "GR-903"),
        ("Paper Lantern Print", "marketing", 60_000, True, "INV-2190"),
        ("Nightshift Crew", "venue", 120_000, False, ""),
    ],
    "low-ceiling-2026-10-08": [
        ("Northline Audio", "production", 90_000, True, "INV-1201"),
        ("Paper Lantern Print", "marketing", 35_000, True, "INV-1208"),
        ("Green Room Market", "hospitality", 25_000, True, "GR-702"),
        ("Nightshift Crew", "venue", 45_000, False, ""),
    ],
    "fable-stone-2026-10-10": [
        ("Northline Audio", "production", 100_000, True, "INV-1233"),
        ("Paper Lantern Print", "marketing", 40_000, True, "INV-1240"),
        ("Green Room Market", "hospitality", 30_000, True, "GR-744"),
        ("Nightshift Crew", "venue", 50_000, False, ""),
    ],
    "rookery-2026-10-14": [
        ("Northline Audio", "production", 110_000, True, "INV-1287"),
        ("Paper Lantern Print", "marketing", 45_000, True, "INV-1294"),
        ("Green Room Market", "hospitality", 35_000, True, "GR-801"),
        ("Nightshift Crew", "venue", 55_000, False, ""),
    ],
    "june-almeida-2026-10-17": [
        ("Northline Audio", "production", 125_000, True, ""),
        ("Paper Lantern Print", "marketing", 50_000, True, "INV-3012"),
        ("Green Room Market", "hospitality", 40_000, True, "GR-1204"),
        ("Nightshift Crew", "venue", 70_000, False, ""),
    ],
}

HISTORICAL = {
    # show key -> (status, approved_day, approved_hour, paid_day, payment_ref, review_note)
    "nia-calder-2026-09-18": (
        "paid",
        "2026-09-19",
        10,
        "2026-09-21",
        "ACH-260919-01",
        "Approved in the Monday review. Flat guarantee, all receipts present.",
    ),
    "harbor-lights-2026-09-20": (
        "paid",
        "2026-09-21",
        10,
        "2026-09-23",
        "ACH-260921-04",
        "Approved. Percentage deal, recoup below cap.",
    ),
    "quiet-hours-2026-09-24": (
        "paid",
        "2026-09-25",
        11,
        "2026-09-28",
        "ACH-260925-02",
        "Approved. VS deal paid the percentage side by a wide margin.",
    ),
    "otis-bell-2026-09-27": (
        "paid",
        "2026-09-28",
        10,
        "2026-09-30",
        "ACH-260928-03",
        "Approved. Flat guarantee, clean packet.",
    ),
    "saltwater-choir-2026-10-01": (
        "paid",
        "2026-10-02",
        10,
        "2026-10-05",
        "ACH-261002-01",
        "Approved. Benefit show, percentage deal.",
    ),
    "mira-tides-2026-10-03": (
        "held",
        "2026-10-04",
        11,
        "",
        "",
        "Held: Clearwater Backline has no receipt for the $1,800 rental. "
        "Recoup is capped at $5,500 and the $250 overage is already house-absorbed. "
        "Reopen when the invoice arrives.",
    ),
}

MEMBER_EMAIL = "manager@lanternroom.test"


def sales_for(key: str) -> list[Sale]:
    return [Sale(*row) for row in SALES[key]]


def expenses_for(key: str) -> list[Expense]:
    return [Expense(amount_cents=row[2], recoupable=row[3]) for row in EXPENSES[key]]


def show_model(row: dict) -> Show:
    return Show(
        id=uid("show", row["key"]),
        show_date=row["show_date"],
        artist=row["artist"],
        deal_type=row["deal_type"],
        guarantee_cents=row["guarantee_cents"],
        percentage_bps=row["percentage_bps"],
        expense_cap_cents=row["expense_cap_cents"],
    )


RECEIPT_THRESHOLD_CENTS = 25_000
COMP_ALLOWANCE = 12
CHECK_ORDER = [
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
]
STATUS_RANK = {"block": 0, "watch": 1, "pass": 2}


def make_review(show: dict, s, paid_tickets: int, comps: int, expenses) -> dict:
    """Build the review the agent would have returned for a historical packet."""
    missing = [
        e for e in expenses
        if e[3] and e[2] >= RECEIPT_THRESHOLD_CENTS and not e[4].strip()
    ]
    small_missing = [
        e for e in expenses
        if e[3] and e[2] < RECEIPT_THRESHOLD_CENTS and not e[4].strip()
    ]
    gross = s.ticket_revenue_cents
    fee_pct = (s.fees_cents / gross * 100) if gross else 0.0
    over_cap_pct = (s.over_cap_cents / s.recoup_cap_cents * 100) if s.recoup_cap_cents else 0.0
    comp_over = max(0, comps - COMP_ALLOWANCE)
    comp_over_pct = (comp_over / COMP_ALLOWANCE * 100) if comp_over else 0.0
    share = percent_of(s.pool_cents, s.percentage_bps)
    payout = s.calculated_payout_cents

    def receipt_detail() -> tuple[str, str]:
        if missing:
            names = ", ".join(f"{m[0]} ({usd(m[2])})" for m in missing)
            return "block", (
                f"Missing receipt for {names}. The policy requires a receipt on every "
                f"recoupable expense of {usd(RECEIPT_THRESHOLD_CENTS)} or more."
            )
        if small_missing:
            names = ", ".join(f"{m[0]} ({usd(m[2])})" for m in small_missing)
            return "watch", (
                f"Receipt missing for {names}, below the {usd(RECEIPT_THRESHOLD_CENTS)} "
                "threshold. Note it, but it does not block the payout."
            )
        return "pass", (
            f"Every recoupable expense of {usd(RECEIPT_THRESHOLD_CENTS)} or more "
            "carries a receipt reference."
        )

    if s.over_cap_cents > 0:
        cap_status = "block" if over_cap_pct > 20 else "watch"
        cap_detail = (
            f"Recoupable expenses total {usd(s.recoupable_total_cents)} against the "
            f"{usd(s.recoup_cap_cents)} cap; {usd(s.over_cap_cents)} is house-absorbed "
            f"({over_cap_pct:.2f}% over)."
        )
    else:
        cap_status = "pass"
        cap_detail = (
            f"Recoupable expenses total {usd(s.recoupable_total_cents)} against the "
            f"{usd(s.recoup_cap_cents)} cap; the full amount is recouped."
        )

    if comp_over:
        comp_status = "block" if comp_over_pct > 50 else "watch"
        comp_detail = (
            f"{comps} comps against a {COMP_ALLOWANCE}-comp allowance; "
            f"{comp_over} over ({comp_over_pct:.2f}%)."
        )
    else:
        comp_status = "pass"
        comp_detail = f"{comps} comps against a {COMP_ALLOWANCE}-comp allowance."

    if show["deal_type"] == "FLAT":
        math_detail = (
            f"FLAT deal: {usd(payout)} equals the {usd(show['guarantee_cents'])} "
            "guarantee; every stored money field ties out."
        )
        floor_detail = (
            f"Calculated payout {usd(payout)} is at least the "
            f"{usd(show['guarantee_cents'])} guarantee."
        )
        floor_status = "pass" if payout >= show["guarantee_cents"] and payout > 0 else "block"
    elif show["deal_type"] == "PERCENTAGE":
        math_detail = (
            f"PERCENTAGE deal: {show['percentage_bps'] / 100:.2f}% of the "
            f"{usd(s.pool_cents)} pool pays {usd(payout)}; every stored money field ties out."
        )
        floor_detail = (
            f"Calculated payout {usd(payout)} is above zero on a played show; "
            "this deal has no guarantee."
            if payout > 0
            else "Calculated payout is zero on a played show; the floor is not met."
        )
        floor_status = "pass" if payout > 0 else "block"
    else:
        if share >= show["guarantee_cents"]:
            math_detail = (
                f"VS deal: the {show['percentage_bps'] / 100:.2f}% share ({usd(share)}) "
                f"beats the {usd(show['guarantee_cents'])} guarantee by "
                f"{usd(share - show['guarantee_cents'])}; payout {usd(payout)}."
            )
        else:
            math_detail = (
                f"VS deal: the {usd(show['guarantee_cents'])} guarantee beats the "
                f"{show['percentage_bps'] / 100:.2f}% share ({usd(share)}) by "
                f"{usd(show['guarantee_cents'] - share)}; payout {usd(payout)}."
            )
        floor_detail = (
            f"Calculated payout {usd(payout)} is at least the "
            f"{usd(show['guarantee_cents'])} guarantee."
        )
        floor_status = "pass" if payout >= show["guarantee_cents"] and payout > 0 else "block"

    receipt_status, receipt_text = receipt_detail()

    findings = [
        {
            "check": "packet_integrity",
            "status": "pass",
            "detail": (
                "The review request, settlement, and show agree; the show is played "
                "and the show date is in the past."
            ),
        },
        {
            "check": "channels",
            "status": "pass",
            "detail": (
                f"Online and door exports both carry a source reference; {paid_tickets} "
                f"paid admissions and {comps} comps reconcile across the two channels."
            ),
        },
        {
            "check": "fees",
            "status": "block" if fee_pct > 8 else "watch" if fee_pct > 5 else "pass",
            "detail": (
                f"{usd(s.fees_cents)} in fees is {fee_pct:.2f}% of "
                f"{usd(gross)} gross ticket revenue. The policy ceiling is 5.00%."
            ),
        },
        {"check": "receipts", "status": receipt_status, "detail": receipt_text},
        {"check": "recoup_cap", "status": cap_status, "detail": cap_detail},
        {"check": "comps", "status": comp_status, "detail": comp_detail},
        {
            "check": "deal_math",
            "status": "pass",
            "detail": math_detail,
        },
        {"check": "payout_floor", "status": floor_status, "detail": floor_detail},
        {
            "check": "prior_payment",
            "status": "pass",
            "detail": "No other settlement points at this show.",
        },
        {
            "check": "reopen_context",
            "status": "pass",
            "detail": "No earlier reopen event on this settlement.",
        },
    ]
    findings.sort(key=lambda f: (STATUS_RANK[f["status"]], CHECK_ORDER.index(f["check"])))

    blocks = [f for f in findings if f["status"] == "block"]
    watches = [f for f in findings if f["status"] == "watch"]
    recommendation = "hold" if blocks or len(watches) >= 2 else "approve"

    if blocks:
        if missing:
            headline = f"Hold: receipt missing for {missing[0][0]}"
            if len(missing) > 1:
                headline = f"Hold: {len(missing)} recoupable receipts missing"
        else:
            headline = f"Hold: {blocks[0]['check'].replace('_', ' ')} needs attention"
    elif comp_over:
        headline = f"Clear to pay {usd(payout)}; comps are over allowance"
    else:
        headline = f"Clear to pay {usd(payout)}"

    if blocks:
        gaps = ", ".join(f"{m[0]} ({usd(m[2])})" for m in missing)
        note = (
            f"The math is right and the calculated payout is {usd(payout)}, but "
            f"{gaps} has no receipt. Hold the payout until the receipt is attached, "
            "then reopen the review."
        )
    elif comp_over:
        note = (
            "Both ticket channels reconcile, the receipts are complete, and the deal "
            f"math ties out. The guest list ran {comp_over} comps over the allowance; "
            f"note it for the next show and pay {usd(payout)}."
        )
    else:
        note = (
            "Both ticket channels reconcile, every required receipt is present, and "
            f"the deal math ties out. Clear to pay {usd(payout)}."
        )

    if blocks:
        confidence = 0.82
    elif len(watches) >= 2:
        confidence = 0.86
    elif watches:
        confidence = 0.91
    else:
        confidence = 0.94

    return {
        "headline": headline,
        "recommendation": recommendation,
        "findings": findings,
        "reviewer_note": note,
        "confidence": confidence,
        "reviewed_at": iso(plus_day(show["show_date"], 1), 9, 2),
    }


def main() -> None:
    tables = ROOT / "tables"
    prepared_at = {}
    review_at = {}
    settled_at = {}
    computed = {}

    for row in SHOWS:
        s = compute(show_model(row), sales_for(row["key"]), expenses_for(row["key"]))
        computed[row["key"]] = s
        prepared_at[row["key"]] = iso(plus_day(row["show_date"], 1), 9, 0)
        review_at[row["key"]] = iso(plus_day(row["show_date"], 1), 9, 2)

    write = csv_writer

    # shows
    rows = []
    for row in SHOWS:
        rows.append(
            {
                "id": uid("show", row["key"]),
                "show_date": row["show_date"],
                "artist": row["artist"],
                "billing": row["billing"],
                "room": "Main Room",
                "deal_type": row["deal_type"],
                "guarantee_cents": row["guarantee_cents"],
                "percentage_bps": row["percentage_bps"],
                "expense_cap_cents": row["expense_cap_cents"],
                "status": "played",
                "notes": row["notes"],
                "external_ref": "LR-" + row["show_date"].replace("-", ""),
            }
        )
    write(tables / "shows", rows, [
        "id", "show_date", "artist", "billing", "room", "deal_type",
        "guarantee_cents", "percentage_bps", "expense_cap_cents", "status",
        "notes", "external_ref",
    ])

    # ticket_sales
    rows = []
    for row in SHOWS:
        for index, (paid, face, fees, comps) in enumerate(SALES[row["key"]]):
            channel = "online" if index == 0 else "door"
            rows.append(
                {
                    "id": uid("sale", f"{row['key']}:{channel}"),
                    "show_id": uid("show", row["key"]),
                    "channel": channel,
                    "paid_quantity": paid,
                    "face_value_cents": face,
                    "fees_cents": fees,
                    "comps": comps,
                    "source_ref": (
                        f"ticketing-{row['show_date']}.csv"
                        if channel == "online"
                        else f"door-sheet-{row['show_date']}.csv"
                    ),
                    "recorded_at": iso(row["show_date"], 23, 30),
                }
            )
    write(tables / "ticket_sales", rows, [
        "id", "show_id", "channel", "paid_quantity", "face_value_cents",
        "fees_cents", "comps", "source_ref", "recorded_at",
    ])

    # expenses
    rows = []
    for row in SHOWS:
        for index, (vendor, category, amount, recoupable, receipt) in enumerate(EXPENSES[row["key"]]):
            rows.append(
                {
                    "id": uid("expense", f"{row['key']}:{index}"),
                    "show_id": uid("show", row["key"]),
                    "vendor": vendor,
                    "category": category,
                    "amount_cents": amount,
                    "recoupable": "true" if recoupable else "false",
                    "receipt_ref": receipt,
                    "incurred_on": row["show_date"],
                    "note": "",
                }
            )
    write(tables / "expenses", rows, [
        "id", "show_id", "vendor", "category", "amount_cents", "recoupable",
        "receipt_ref", "incurred_on", "note",
    ])

    # settlements
    rows = []
    for row in SHOWS:
        key = row["key"]
        if key not in HISTORICAL:
            continue
        status, approved_day, approved_hour, paid_day, payment_ref, review_note = HISTORICAL[key]
        s = computed[key]
        paid_tickets = sum(x[0] for x in SALES[key])
        comps = sum(x[3] for x in SALES[key])
        review = make_review(row, s, paid_tickets, comps, EXPENSES[key])
        approved_at = iso(approved_day, approved_hour, 15) if status == "paid" else None
        paid_at = iso(paid_day, 16, 5) if paid_day else None
        rows.append(
            {
                "id": uid("settlement", key),
                "show_id": uid("show", key),
                "status": status,
                "ticket_revenue_cents": s.ticket_revenue_cents,
                "fees_cents": s.fees_cents,
                "net_box_office_cents": s.net_box_office_cents,
                "recoupable_total_cents": s.recoupable_total_cents,
                "recoup_cap_cents": s.recoup_cap_cents,
                "recouped_cents": s.recouped_cents,
                "over_cap_cents": s.over_cap_cents,
                "pool_cents": s.pool_cents,
                "deal_type": s.deal_type,
                "guarantee_cents": s.guarantee_cents,
                "percentage_bps": s.percentage_bps,
                "calculated_payout_cents": s.calculated_payout_cents,
                "approved_payout_cents": s.calculated_payout_cents if status == "paid" else "",
                "agent_review": json.dumps(review, separators=(",", ":")),
                "review_note": review_note,
                "prepared_at": prepared_at[key],
                "approved_at": approved_at or "",
                "approved_by": MEMBER_EMAIL if status == "paid" else "",
                "paid_at": paid_at or "",
                "payment_ref": payment_ref,
                "calculation_version": "2026-10",
            }
        )
    write(tables / "settlements", rows, [
        "id", "show_id", "status", "ticket_revenue_cents", "fees_cents",
        "net_box_office_cents", "recoupable_total_cents", "recoup_cap_cents",
        "recouped_cents", "over_cap_cents", "pool_cents", "deal_type",
        "guarantee_cents", "percentage_bps", "calculated_payout_cents",
        "approved_payout_cents", "agent_review", "review_note", "prepared_at",
        "approved_at", "approved_by", "paid_at", "payment_ref", "calculation_version",
    ])

    # settlement_events
    rows = []
    for index, row in enumerate(SHOWS):
        key = row["key"]
        if key not in HISTORICAL:
            continue
        status, approved_day, approved_hour, paid_day, _, review_note = HISTORICAL[key]
        s = computed[key]
        sid = uid("settlement", key)
        paid_tickets = sum(x[0] for x in SALES[key])
        comps = sum(x[3] for x in SALES[key])
        review = make_review(row, s, paid_tickets, comps, EXPENSES[key])
        rows.extend(
            [
                {
                    "id": uid("event", f"{key}:prepared"),
                    "settlement_id": sid,
                    "kind": "prepared",
                    "actor": "prepare_settlements",
                    "detail": (
                        f"Computed from 2 ticket channels and {len(EXPENSES[key])} expenses. "
                        f"Calculated payout {usd(s.calculated_payout_cents)}."
                    ),
                    "occurred_at": prepared_at[key],
                },
                {
                    "id": uid("event", f"{key}:review_ready"),
                    "settlement_id": sid,
                    "kind": "review_ready",
                    "actor": "settlement-reviewer",
                    "detail": review["headline"] + ". " + review["reviewer_note"],
                    "occurred_at": review_at[key],
                },
                {
                    "id": uid("event", f"{key}:decision"),
                    "settlement_id": sid,
                    "kind": "approved" if status == "paid" else "held",
                    "actor": MEMBER_EMAIL,
                    "detail": (
                        f"Payout approved at {usd(s.calculated_payout_cents)}. {review_note}"
                        if status == "paid"
                        else review_note
                    ),
                    "occurred_at": iso(approved_day, approved_hour, 15),
                },
            ]
        )
        if status == "paid":
            rows.append(
                {
                    "id": uid("event", f"{key}:paid"),
                    "settlement_id": sid,
                    "kind": "paid",
                    "actor": MEMBER_EMAIL,
                    "detail": f"Payment recorded. Reference {HISTORICAL[key][4]}.",
                    "occurred_at": iso(paid_day, 16, 5),
                }
            )
    write(tables / "settlement_events", rows, [
        "id", "settlement_id", "kind", "actor", "detail", "occurred_at",
    ])

    # review_requests (closed history only)
    rows = []
    for row in SHOWS:
        key = row["key"]
        if key not in HISTORICAL:
            continue
        status, approved_day, approved_hour, _, _, _ = HISTORICAL[key]
        rows.append(
            {
                "id": uid("review", f"{key}:initial"),
                "settlement_id": uid("settlement", key),
                "status": "closed",
                "reason": "Monthly settlement cycle",
                "requested_by": "prepare_settlements",
                "requested_at": prepared_at[key],
                "closed_at": iso(approved_day, approved_hour, 15),
            }
        )
    write(tables / "review_requests", rows, [
        "id", "settlement_id", "status", "reason", "requested_by",
        "requested_at", "closed_at",
    ])

    # settings
    write(tables / "settings", [
        {
            "id": uid("settings", "lantern-room"),
            "venue_name": "The Lantern Room",
            "room_name": "Main Room",
            "approval_member_id": "",
            "comp_allowance": 12,
            "receipt_threshold_cents": 25_000,
            "currency": "USD",
            "activated": "true",
            "last_cycle_at": "2026-10-04T09:00:00Z",
        }
    ], [
        "id", "venue_name", "room_name", "approval_member_id", "comp_allowance",
        "receipt_threshold_cents", "currency", "activated", "last_cycle_at",
    ])

    print("Seed written.")
    for row in SHOWS:
        key = row["key"]
        s = computed[key]
        state = HISTORICAL[key][0] if key in HISTORICAL else "not prepared"
        print(
            f"  {row['show_date']}  {row['artist']:<22} {row['deal_type']:<10} "
            f"payout {usd(s.calculated_payout_cents):>10}  {state}"
        )


def csv_writer(directory: Path, rows: list[dict], fieldnames: list[str]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "data.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    print(f"wrote {path.relative_to(ROOT)} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
