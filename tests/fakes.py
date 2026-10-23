from __future__ import annotations

import csv
import importlib.util
import sys
import types
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TABLES = ROOT / "tables"


class FakeTable:
    def __init__(self, name: str, rows: list[dict[str, Any]]) -> None:
        self.name = name
        self.rows = rows

    def get(self, record_id: str) -> dict[str, Any]:
        for row in self.rows:
            if str(row.get("id")) == str(record_id):
                return row
        raise KeyError(f"{self.name} has no row {record_id}")

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        row = dict(data)
        row.setdefault("id", str(uuid.uuid4()))
        self.rows.append(row)
        return row

    def update(self, record_id: str, data: dict[str, Any]) -> dict[str, Any]:
        row = self.get(record_id)
        row.update(data)
        return row


class FakeRecords:
    def __init__(self, tables: dict[str, FakeTable]) -> None:
        self.tables = tables

    def list_all(
        self,
        name: str,
        page_size: int = 500,
        filter: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(self.tables.setdefault(name, FakeTable(name, [])).rows)
        for clause in filter or []:
            field = clause["field"]
            value = str(clause["value"])
            if clause["op"] == "eq":
                rows = [row for row in rows if str(row.get(field)) == value]
        return rows


class FakePod:
    current: "FakePod | None" = None

    def __init__(self, tables: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self.tables: dict[str, FakeTable] = {
            name: FakeTable(name, rows) for name, rows in (tables or {}).items()
        }
        self.records = FakeRecords(self.tables)

    @classmethod
    def from_env(cls) -> "FakePod":
        if cls.current is None:
            raise RuntimeError("FakePod.current is not set")
        return cls.current

    def table(self, name: str) -> FakeTable:
        return self.tables.setdefault(name, FakeTable(name, []))


class FakeContext:
    def __init__(self, email: str = "manager@lanternroom.test", user_id: str = "user-1") -> None:
        self.user_email = email
        self.user_id = user_id


def read_table(name: str) -> list[dict[str, Any]]:
    with (TABLES / name / "data.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def seeded_pod() -> FakePod:
    return FakePod({
        "shows": read_table("shows"),
        "ticket_sales": read_table("ticket_sales"),
        "expenses": read_table("expenses"),
        "settlements": read_table("settlements"),
        "settlement_events": read_table("settlement_events"),
        "review_requests": read_table("review_requests"),
        "settings": read_table("settings"),
    })


def load_function(name: str):
    fake_sdk = types.ModuleType("lemma_sdk")
    fake_sdk.FunctionContext = FakeContext
    fake_sdk.Pod = FakePod
    sys.modules["lemma_sdk"] = fake_sdk

    module_name = f"loadout_{name}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        ROOT / "functions" / name / "code.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def settlement_row(seed_row: dict[str, Any] | None = None, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "settlement-1",
        "show_id": "show-1",
        "status": "awaiting_approval",
        "ticket_revenue_cents": 100_000,
        "fees_cents": 4_000,
        "net_box_office_cents": 96_000,
        "recoupable_total_cents": 20_000,
        "recoup_cap_cents": 50_000,
        "recouped_cents": 20_000,
        "over_cap_cents": 0,
        "pool_cents": 76_000,
        "deal_type": "PERCENTAGE",
        "guarantee_cents": 0,
        "percentage_bps": 7_000,
        "calculated_payout_cents": 53_200,
        "approved_payout_cents": None,
        "agent_review": {},
        "review_note": "",
        "prepared_at": "2026-10-01T09:00:00Z",
        "approved_at": None,
        "approved_by": None,
        "paid_at": None,
        "payment_ref": "",
        "calculation_version": "2026-10",
    }
    if seed_row:
        row.update(seed_row)
    row.update(overrides)
    return row


def request_row(status: str = "open", settlement_id: str = "settlement-1") -> dict[str, Any]:
    return {
        "id": "request-1",
        "settlement_id": settlement_id,
        "status": status,
        "reason": "Test review",
        "requested_by": "test",
        "requested_at": "2026-10-01T09:00:00Z",
        "closed_at": None,
    }
