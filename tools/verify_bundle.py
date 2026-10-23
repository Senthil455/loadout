"""Structural and arithmetic checks for the Loadout bundle.

Run from the repository root:

    python tools/verify_bundle.py

The verifier is deliberately dependency-free. It checks the things that break
silently in a pod bundle: a CSV header that drifted from the table schema, a
foreign key that points nowhere, a workflow edge to a deleted node, a review
that does not use the agent's check ids, or a settlement whose stored payout no
longer matches the rows it was built from.
"""

from __future__ import annotations

import ast
import csv
import json
import re
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from settlement_math import Expense, Sale, Show, compute  # noqa: E402

CHECK_IDS = [
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
TABLE_TYPES = {
    "TEXT",
    "FILE_PATH",
    "INTEGER",
    "FLOAT",
    "BOOLEAN",
    "JSON",
    "DATE",
    "DATETIME",
    "UUID",
    "USER",
    "VECTOR",
    "SERIAL",
    "ENUM",
}
SETTLEMENT_STATUSES = {"draft", "awaiting_approval", "approved", "held", "paid"}
EVENT_KINDS = {"prepared", "review_ready", "approved", "held", "paid", "reopened"}
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

failures: list[str] = []
checks = 0


def check(condition: bool, message: str) -> bool:
    global checks
    checks += 1
    if not condition:
        failures.append(message)
    return condition


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        failures.append(f"{rel(path)} is not valid JSON: {exc}")
        return {}
    check(isinstance(value, dict), f"{rel(path)} must contain a JSON object")
    return value if isinstance(value, dict) else {}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def text_files() -> Iterable[Path]:
    skip = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip for part in path.parts):
            continue
        if path.suffix in {".pyc", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".mp4", ".webm"}:
            continue
        yield path


def verify_ascii() -> None:
    for path in text_files():
        try:
            body = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"{rel(path)} is not UTF-8 text")
            continue
        bad = [char for char in body if ord(char) > 127]
        check(not bad, f"{rel(path)} contains non-ASCII characters: {sorted(set(bad))[:5]}")


def verify_pod() -> None:
    pod = load_json(ROOT / "pod.json")
    check(pod.get("name") == "loadout", "pod.json name must be loadout")
    check(pod.get("format_version") == 3, "pod.json format_version must be 3")
    check(bool(pod.get("description")), "pod.json needs a description")


def verify_tables() -> dict[str, tuple[dict[str, Any], list[dict[str, str]]]]:
    tables: dict[str, tuple[dict[str, Any], list[dict[str, str]]]] = {}
    expected = {
        "shows",
        "ticket_sales",
        "expenses",
        "settlements",
        "settlement_events",
        "review_requests",
        "settings",
    }
    found = {p.name for p in (ROOT / "tables").iterdir() if p.is_dir()}
    check(found == expected, f"tables/ must contain exactly {sorted(expected)}, found {sorted(found)}")

    raw: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
    for name in sorted(expected):
        table_path = ROOT / "tables" / name / f"{name}.json"
        csv_path = ROOT / "tables" / name / "data.csv"
        check(table_path.exists(), f"missing {rel(table_path)}")
        check(csv_path.exists(), f"missing {rel(csv_path)}")
        if not table_path.exists() or not csv_path.exists():
            continue
        schema = load_json(table_path)
        check(schema.get("name") == name, f"{rel(table_path)} name must be {name}")
        columns = schema.get("columns")
        check(isinstance(columns, list) and bool(columns), f"{name} needs columns")
        columns = columns if isinstance(columns, list) else []
        names = [column.get("name") for column in columns if isinstance(column, dict)]
        check(len(names) == len(set(names)), f"{name} has duplicate column names")
        for column in columns:
            if not isinstance(column, dict):
                failures.append(f"{name} has a non-object column")
                continue
            column_name = column.get("name")
            column_type = column.get("type")
            check(bool(column_name), f"{name} has a column without a name")
            check(column_type in TABLE_TYPES, f"{name}.{column_name} has invalid type {column_type!r}")
            if column_type == "ENUM":
                options = column.get("options")
                check(
                    isinstance(options, list) and len(options) > 0,
                    f"{name}.{column_name} ENUM needs options",
                )
            foreign = column.get("foreign_key")
            if foreign:
                target = str(foreign.get("references", ""))
                check(
                    target.split(".")[0] in expected,
                    f"{name}.{column_name} foreign key references unknown table {target!r}",
                )
        header, rows = read_csv(csv_path)
        check(bool(rows), f"{name}/data.csv must have at least one row")
        allowed = set(names) | {"id"}
        check(
            set(header) <= allowed,
            f"{name}/data.csv has columns missing from the schema: {sorted(set(header) - allowed)}",
        )
        missing = [column for column in names if column not in header]
        check(not missing, f"{name}/data.csv is missing declared columns: {missing}")
        raw[name] = (header, rows)

    # Foreign keys and scalar types are checked after every table is loaded.
    for name, (header, rows) in raw.items():
        schema = load_json(ROOT / "tables" / name / f"{name}.json")
        columns = {
            column["name"]: column
            for column in schema.get("columns", [])
            if isinstance(column, dict) and column.get("name")
        }
        seen_ids: set[str] = set()
        unique_seen: dict[str, set[str]] = defaultdict(set)
        for index, row in enumerate(rows, start=2):
            row_id = row.get("id", "")
            check(bool(row_id), f"{name} row {index} has no id")
            check(row_id not in seen_ids, f"{name} row {index} repeats id {row_id}")
            seen_ids.add(row_id)
            for column_name, column in columns.items():
                value = (row.get(column_name) or "").strip()
                if column.get("required"):
                    check(bool(value), f"{name} row {index} column {column_name} is required")
                if not value:
                    continue
                column_type = column.get("type")
                if column_type == "INTEGER":
                    check(_is_int(value), f"{name} row {index} {column_name} is not an integer: {value!r}")
                elif column_type == "FLOAT":
                    check(_is_float(value), f"{name} row {index} {column_name} is not a float: {value!r}")
                elif column_type == "BOOLEAN":
                    check(value.lower() in {"true", "false"}, f"{name} row {index} {column_name} is not a boolean")
                elif column_type == "DATE":
                    check(_is_date(value), f"{name} row {index} {column_name} is not a date: {value!r}")
                elif column_type == "DATETIME":
                    check(_is_datetime(value), f"{name} row {index} {column_name} is not a datetime: {value!r}")
                elif column_type == "UUID":
                    check(_is_uuid(value), f"{name} row {index} {column_name} is not a UUID: {value!r}")
                elif column_type == "JSON":
                    try:
                        json.loads(value)
                    except json.JSONDecodeError:
                        failures.append(f"{name} row {index} {column_name} is not JSON")
                        checks += 1
                elif column_type == "ENUM":
                    check(
                        value in column.get("options", []),
                        f"{name} row {index} {column_name} is not one of {column.get('options')}",
                    )
                if column.get("unique"):
                    check(
                        value not in unique_seen[column_name],
                        f"{name} row {index} {column_name} repeats {value!r}",
                    )
                    unique_seen[column_name].add(value)
        for column_name, column in columns.items():
            foreign = column.get("foreign_key")
            if not foreign:
                continue
            target_table, target_column = str(foreign["references"]).split(".", 1)
            target_rows = raw[target_table][1]
            target_ids = {row.get(target_column, "") for row in target_rows}
            for index, row in enumerate(rows, start=2):
                value = (row.get(column_name) or "").strip()
                if value:
                    check(
                        value in target_ids,
                        f"{name} row {index} {column_name} points at missing {target_table}.{target_column} {value}",
                    )
        tables[name] = (schema, rows)
    return tables


def verify_seed(tables: dict[str, tuple[dict[str, Any], list[dict[str, str]]]]) -> None:
    shows = {row["id"]: row for row in tables["shows"][1]}
    sales_by_show: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in tables["ticket_sales"][1]:
        sales_by_show[row["show_id"]].append(row)
    expenses_by_show: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in tables["expenses"][1]:
        expenses_by_show[row["show_id"]].append(row)

    check(len(shows) == 10, f"seed must have 10 shows, found {len(shows)}")
    check(
        {row["status"] for row in shows.values()} == {"played"},
        "every seeded show must be played so the cycle can settle it",
    )
    for show_id, show in shows.items():
        rows = sales_by_show[show_id]
        check(
            {row["channel"] for row in rows} == {"online", "door"},
            f"show {show['artist']} must have one online and one door row",
        )
        for row in rows:
            check(bool(row["source_ref"]), f"show {show['artist']} has a sales row without a source_ref")

    expected_missing = {
        ("Mira and the Tides", "Clearwater Backline", 180_000),
        ("June Almeida", "Northline Audio", 125_000),
    }
    actual_missing = {
        (show["artist"], row["vendor"], int(row["amount_cents"]))
        for show_id, show in shows.items()
        for row in expenses_by_show[show_id]
        if row["recoupable"].lower() == "true"
        and int(row["amount_cents"]) >= 25_000
        and not row["receipt_ref"].strip()
    }
    check(actual_missing == expected_missing, f"missing-receipt set changed: {sorted(actual_missing)}")

    # Every show has a reviewed demo payout, settled or waiting for the first cycle.
    for show_id, show in shows.items():
        computed = compute(
            Show(
                id=show["id"],
                show_date=show["show_date"],
                artist=show["artist"],
                deal_type=show["deal_type"],
                guarantee_cents=int(show["guarantee_cents"]),
                percentage_bps=int(show["percentage_bps"]),
                expense_cap_cents=int(show["expense_cap_cents"]),
            ),
            [Sale(
                paid_quantity=int(sale["paid_quantity"]),
                face_value_cents=int(sale["face_value_cents"]),
                fees_cents=int(sale["fees_cents"]),
                comps=int(sale["comps"]),
            ) for sale in sales_by_show[show_id]],
            [Expense(
                amount_cents=int(expense["amount_cents"]),
                recoupable=expense["recoupable"].lower() == "true",
            ) for expense in expenses_by_show[show_id]],
        )
        check(
            computed.calculated_payout_cents == EXPECTED_PAYOUTS[show["artist"]],
            f"{show['artist']} payout is {computed.calculated_payout_cents}, expected {EXPECTED_PAYOUTS[show['artist']]}",
        )

    settlements = tables["settlements"][1]
    check(len(settlements) == 6, f"seed must have 6 historical settlements, found {len(settlements)}")
    statuses = [row["status"] for row in settlements]
    check(statuses.count("paid") == 5, "seed must have five paid settlements")
    check(statuses.count("held") == 1, "seed must have one held settlement")

    for row in settlements:
        show = shows[row["show_id"]]
        model = Show(
            id=show["id"],
            show_date=show["show_date"],
            artist=show["artist"],
            deal_type=show["deal_type"],
            guarantee_cents=int(show["guarantee_cents"]),
            percentage_bps=int(show["percentage_bps"]),
            expense_cap_cents=int(show["expense_cap_cents"]),
        )
        computed = compute(
            model,
            [Sale(
                paid_quantity=int(sale["paid_quantity"]),
                face_value_cents=int(sale["face_value_cents"]),
                fees_cents=int(sale["fees_cents"]),
                comps=int(sale["comps"]),
            ) for sale in sales_by_show[show["id"]]],
            [Expense(
                amount_cents=int(expense["amount_cents"]),
                recoupable=expense["recoupable"].lower() == "true",
            ) for expense in expenses_by_show[show["id"]]],
        )
        for field in (
            "ticket_revenue_cents",
            "fees_cents",
            "net_box_office_cents",
            "recoupable_total_cents",
            "recoup_cap_cents",
            "recouped_cents",
            "over_cap_cents",
            "pool_cents",
            "calculated_payout_cents",
        ):
            check(
                int(row[field]) == getattr(computed, field),
                f"{show['artist']} {field} is {row[field]}, computed {getattr(computed, field)}",
            )
        check(row["deal_type"] == show["deal_type"], f"{show['artist']} deal_type drifted")
        check(
            int(row["guarantee_cents"]) == int(show["guarantee_cents"]),
            f"{show['artist']} guarantee drifted",
        )
        check(
            int(row["percentage_bps"]) == int(show["percentage_bps"]),
            f"{show['artist']} percentage drifted",
        )
        check(
            int(row["calculated_payout_cents"]) == EXPECTED_PAYOUTS[show["artist"]],
            f"{show['artist']} payout changed from the reviewed demo number",
        )
        review = json.loads(row["agent_review"])
        verify_review(review, show["artist"], row["status"])
        if row["status"] == "paid":
            check(bool(row["approved_at"]), f"{show['artist']} paid without approved_at")
            check(bool(row["approved_by"]), f"{show['artist']} paid without approved_by")
            check(bool(row["paid_at"]), f"{show['artist']} paid without paid_at")
            check(bool(row["payment_ref"]), f"{show['artist']} paid without a payment reference")
            check(
                int(row["approved_payout_cents"]) == int(row["calculated_payout_cents"]),
                f"{show['artist']} approved amount differs from the calculation",
            )
        elif row["status"] == "held":
            check(not row["approved_at"], f"{show['artist']} held but approved_at is set")
            check(not row["approved_by"], f"{show['artist']} held but approved_by is set")
            check(not row["paid_at"], f"{show['artist']} held but paid_at is set")
            check(bool(row["review_note"]), f"{show['artist']} held without a reason")

    # The four later shows must not have a settlement yet.
    settled_shows = {row["show_id"] for row in settlements}
    un_settled = [show for show_id, show in shows.items() if show_id not in settled_shows]
    check(len(un_settled) == 4, f"expected 4 shows waiting for the first cycle, found {len(un_settled)}")
    check(
        {show["artist"] for show in un_settled}
        == {"Low Ceiling", "Fable & Stone", "Rookery", "June Almeida"},
        "the wrong shows are waiting for the first cycle",
    )

    requests = tables["review_requests"][1]
    check(len(requests) == 6, "seed should have six historical review requests")
    check(
        all(request["status"] == "closed" for request in requests),
        "seeded review requests must be closed so the first cycle starts clean",
    )
    request_settlements = {request["settlement_id"] for request in requests}
    check(
        request_settlements == {row["id"] for row in settlements},
        "every historical settlement needs one closed review request",
    )

    events = tables["settlement_events"][1]
    by_settlement: dict[str, list[str]] = defaultdict(list)
    for event in events:
        check(event["kind"] in EVENT_KINDS, f"unknown event kind {event['kind']!r}")
        by_settlement[event["settlement_id"]].append(event["kind"])
    for row in settlements:
        kinds = by_settlement[row["id"]]
        check("prepared" in kinds, f"{row['id']} has no prepared event")
        check("review_ready" in kinds, f"{row['id']} has no review_ready event")
        if row["status"] == "paid":
            check("approved" in kinds, f"{row['id']} paid without an approved event")
            check("paid" in kinds, f"{row['id']} paid without a paid event")
        if row["status"] == "held":
            check("held" in kinds, f"{row['id']} held without a held event")

    settings = tables["settings"][1]
    check(len(settings) == 1, "settings must have exactly one row")
    check(settings[0]["activated"].lower() == "true", "settings.activated must be true")
    check(
        not settings[0]["approval_member_id"].strip(),
        "approval_member_id must start blank so the app can claim the desk",
    )


def verify_review(review: dict[str, Any], artist: str, status: str) -> None:
    for key in ("headline", "recommendation", "findings", "reviewer_note", "confidence", "reviewed_at"):
        check(key in review, f"{artist} review is missing {key}")
    findings = review.get("findings", [])
    check(isinstance(findings, list) and len(findings) >= 6, f"{artist} review needs at least six findings")
    ids = [finding.get("check") for finding in findings]
    check(len(ids) == len(set(ids)), f"{artist} review repeats a check id")
    check(set(ids) <= set(CHECK_IDS), f"{artist} review uses unknown check ids: {sorted(set(ids) - set(CHECK_IDS))}")
    for finding in findings:
        check(finding.get("status") in STATUS_RANK, f"{artist} finding {finding.get('check')} has a bad status")
        check(bool(str(finding.get("detail", "")).strip()), f"{artist} finding {finding.get('check')} has no detail")
    rank = [STATUS_RANK.get(finding.get("status"), 9) for finding in findings]
    check(rank == sorted(rank), f"{artist} findings are not ordered blocks, watches, then passes")
    blocks = sum(1 for finding in findings if finding.get("status") == "block")
    watches = sum(1 for finding in findings if finding.get("status") == "watch")
    expected = "hold" if blocks or watches >= 2 else "approve"
    check(
        review.get("recommendation") == expected,
        f"{artist} recommendation is {review.get('recommendation')!r}, expected {expected!r}",
    )
    check(0 <= float(review.get("confidence", -1)) <= 1, f"{artist} confidence is out of range")
    if status == "held":
        check(blocks > 0, f"{artist} is held without a blocking finding")


def verify_files() -> None:
    policy = ROOT / "files" / "policy"
    for name in ("settlement-policy.md", "artist-deal-guide.md", "close-checklist.md"):
        path = policy / name
        check(path.exists(), f"missing policy file {rel(path)}")
        if path.exists():
            check(len(path.read_text(encoding="utf-8")) > 400, f"{rel(path)} looks empty")
    folder = policy / ".folder.json"
    check(folder.exists(), "files/policy needs .folder.json")
    if folder.exists():
        check(load_json(folder).get("visibility") == "POD", "policy folder must be POD-visible")
    manifest = ROOT / "files" / ".files.json"
    check(manifest.exists(), "files/.files.json is missing")
    if manifest.exists():
        data = load_json(manifest)
        entries = data.get("files", [])
        check(isinstance(entries, list) and len(entries) == 3, "files/.files.json should list three policy files")
        for entry in entries:
            path = ROOT / "files" / str(entry.get("path", "")).lstrip("/")
            check(path.exists(), f".files.json points at missing {entry.get('path')}")
            check(entry.get("visibility") == "POD", f"{entry.get('path')} must be POD-visible")


def verify_functions() -> None:
    functions_dir = ROOT / "functions"
    expected = {
        "prepare_settlements",
        "build_review_packet",
        "attach_review",
        "record_review",
        "mark_paid",
        "reopen_settlement",
    }
    found = {path.name for path in functions_dir.iterdir() if path.is_dir()}
    check(found == expected, f"functions/ must contain {sorted(expected)}, found {sorted(found)}")
    for name in sorted(expected):
        manifest_path = functions_dir / name / f"{name}.json"
        code_path = functions_dir / name / "code.py"
        check(manifest_path.exists(), f"missing {rel(manifest_path)}")
        check(code_path.exists(), f"missing {rel(code_path)}")
        if not manifest_path.exists() or not code_path.exists():
            continue
        manifest = load_json(manifest_path)
        check(manifest.get("name") == name, f"{rel(manifest_path)} name must be {name}")
        check(manifest.get("type") == "API", f"{name} must be an API function")
        check(manifest.get("code") == {"$file": "code.py"}, f"{name} must load code.py")
        source = code_path.read_text(encoding="utf-8")
        check(f"#function_name: {name}" in source, f"{name} code header has the wrong function name")
        check("#input_type_name:" in source, f"{name} code header has no input type")
        check("#output_type_name:" in source, f"{name} code header has no output type")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            failures.append(f"{rel(code_path)} does not parse: {exc}")
            continue
        async_defs = [node.name for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
        check(name in async_defs, f"{name} has no top-level async function named {name}")
        grants = manifest.get("permissions", {}).get("grants", [])
        for grant in grants:
            resource_type = grant.get("resource_type")
            resource_name = grant.get("resource_name")
            if resource_type == "datastore_table":
                check(
                    (ROOT / "tables" / str(resource_name)).is_dir(),
                    f"{name} grants access to missing table {resource_name}",
                )
            elif resource_type == "folder":
                check(
                    (ROOT / "files" / str(resource_name).lstrip("/")).is_dir(),
                    f"{name} grants access to missing folder {resource_name}",
                )
            else:
                failures.append(f"{name} has an unexpected grant type {resource_type!r}")
                checks += 1

    packet_path = functions_dir / "build_review_packet" / "build_review_packet.json"
    if packet_path.exists():
        packet_manifest = load_json(packet_path)
        grants = packet_manifest.get("permissions", {}).get("grants", [])
        granted = {grant.get("resource_name") for grant in grants}
        expected_tables = {
            "settings",
            "shows",
            "ticket_sales",
            "expenses",
            "settlements",
            "review_requests",
            "settlement_events",
        }
        check(
            granted == expected_tables,
            f"build_review_packet must read exactly {sorted(expected_tables)}, found {sorted(granted)}",
        )
        for grant in grants:
            ids = set(grant.get("permission_ids", []))
            check(
                not any(identifier.endswith((".write", ".create", ".delete")) for identifier in ids),
                f"build_review_packet must stay read-only, found {sorted(ids)}",
            )


def verify_agent() -> None:
    path = ROOT / "agents" / "settlement-reviewer"
    manifest_path = path / "settlement-reviewer.json"
    instruction_path = path / "instruction.md"
    check(manifest_path.exists(), f"missing {rel(manifest_path)}")
    check(instruction_path.exists(), f"missing {rel(instruction_path)}")
    if not manifest_path.exists() or not instruction_path.exists():
        return
    manifest = load_json(manifest_path)
    check(manifest.get("name") == "settlement-reviewer", "agent name must be settlement-reviewer")
    check(manifest.get("instruction") == {"$file": "instruction.md"}, "agent must load instruction.md")
    check(
        manifest.get("toolsets") == [],
        "agent must run without toolsets; the packet builder is the only reader",
    )
    check(
        manifest.get("permissions", {}).get("grants") == [],
        "agent must hold no grants; the packet builder owns every table read",
    )
    input_schema = manifest.get("input_schema", {})
    properties = input_schema.get("properties", {})
    check("packet" in properties, "agent input schema must accept the evidence packet")
    check(
        "packet" in (input_schema.get("required") or []),
        "agent input schema must require the evidence packet",
    )
    instruction = instruction_path.read_text(encoding="utf-8")
    for check_id in CHECK_IDS:
        check(check_id in instruction, f"agent instruction does not mention check {check_id}")
    check("cannot move money" in instruction.lower(), "agent must state it cannot move money")
    check("final_result" in instruction, "agent must tell the model how to return the result")
    check("_cents" in instruction and "Divide by 100" in instruction, "agent must explain cents formatting")


def verify_workflows() -> None:
    workflows_dir = ROOT / "workflows"
    expected = {"settlement-cycle", "settlement-approval"}
    found = {path.name for path in workflows_dir.iterdir() if path.is_dir()}
    check(found == expected, f"workflows/ must contain {sorted(expected)}, found {sorted(found)}")
    functions = {path.name for path in (ROOT / "functions").iterdir() if path.is_dir()}
    agents = {path.name for path in (ROOT / "agents").iterdir() if path.is_dir()}
    node_types = {"FUNCTION", "AGENT", "DECISION", "FORM", "END", "LOOP", "TIME", "WAIT_UNTIL"}
    for name in sorted(expected):
        path = workflows_dir / name / f"{name}.json"
        check(path.exists(), f"missing {rel(path)}")
        if not path.exists():
            continue
        workflow = load_json(path)
        check(workflow.get("name") == name, f"{rel(path)} name must be {name}")
        start = workflow.get("start", {})
        check(start.get("type") in {"SCHEDULED", "DATASTORE_EVENT", "FORM", "MANUAL"}, f"{name} has an invalid start type")
        nodes = workflow.get("nodes", [])
        edges = workflow.get("edges", [])
        check(isinstance(nodes, list) and nodes, f"{name} needs nodes")
        check(isinstance(edges, list) and edges, f"{name} needs edges")
        ids = [node.get("id") for node in nodes]
        check(len(ids) == len(set(ids)), f"{name} has duplicate node ids")
        node_by_id = {node.get("id"): node for node in nodes}
        if name == "settlement-approval":
            check("build_packet" in node_by_id, "approval workflow needs a build_packet node")
            check(
                any(
                    edge.get("source") == "build_packet" and edge.get("target") == "review"
                    for edge in edges
                ),
                "approval workflow must run build_packet before review",
            )
            review_node = node_by_id.get("review", {})
            mapping = review_node.get("config", {}).get("input_mapping", {})
            packet_binding = mapping.get("packet", {})
            check(
                packet_binding.get("type") == "expression"
                and packet_binding.get("value") == "build_packet.packet",
                "review node must receive build_packet.packet",
            )
        for node in nodes:
            node_id = node.get("id")
            node_type = node.get("type")
            check(node_type in node_types, f"{name}.{node_id} has invalid type {node_type!r}")
            if node_type == "FUNCTION":
                function_name = node.get("config", {}).get("function_name")
                check(function_name in functions, f"{name}.{node_id} calls missing function {function_name!r}")
            if node_type == "AGENT":
                agent_name = node.get("config", {}).get("agent_name")
                check(agent_name in agents, f"{name}.{node_id} calls missing agent {agent_name!r}")
            if node_type == "FORM":
                schema = node.get("config", {}).get("input_schema")
                check(isinstance(schema, dict) and schema.get("type") == "object", f"{name}.{node_id} needs an object input_schema")
                expression = node.get("config", {}).get("assignee_pod_member_id_expression")
                if expression:
                    root = str(expression).split(".")[0]
                    check(root in node_by_id or root == "start", f"{name}.{node_id} assignee references unknown node {root}")
            mapping = node.get("config", {}).get("input_mapping", {})
            if isinstance(mapping, dict):
                for key, binding in mapping.items():
                    if isinstance(binding, dict) and binding.get("type") == "expression":
                        root = str(binding.get("value", "")).split(".")[0]
                        check(
                            root in node_by_id or root in {"start", "loop"},
                            f"{name}.{node_id}.{key} references unknown expression root {root}",
                        )
        incoming: dict[str, int] = defaultdict(int)
        outgoing: dict[str, int] = defaultdict(int)
        edge_ids = set()
        rule_targets: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            edge_id = edge.get("id")
            source = edge.get("source")
            target = edge.get("target")
            check(bool(edge_id) and edge_id not in edge_ids, f"{name} has a duplicate or missing edge id {edge_id!r}")
            edge_ids.add(edge_id)
            check(source in node_by_id, f"{name} edge {edge_id} has unknown source {source!r}")
            check(target in node_by_id, f"{name} edge {edge_id} has unknown target {target!r}")
            incoming[target] += 1
            outgoing[source] += 1
        for node in nodes:
            node_id = node.get("id")
            if node.get("type") == "END":
                check(outgoing[node_id] == 0, f"{name}.{node_id} is END but has outgoing edges")
                continue
            check(outgoing[node_id] > 0, f"{name}.{node_id} has no outgoing edge")
            if node.get("type") == "DECISION":
                rules = node.get("config", {}).get("rules", [])
                for rule in rules:
                    target = rule.get("next_node_id")
                    check(target in node_by_id, f"{name}.{node_id} rule points at unknown node {target!r}")
                    rule_targets[node_id].add(target)
                defaults = [
                    edge for edge in edges
                    if edge.get("source") == node_id and edge.get("target") not in rule_targets[node_id]
                ]
                check(bool(defaults), f"{name}.{node_id} needs a default edge")
        entries = [node_id for node_id in ids if incoming[node_id] == 0]
        check(len(entries) == 1, f"{name} must have exactly one entry node, found {entries}")
        if len(entries) == 1:
            reachable = set()
            stack = [entries[0]]
            adjacency: dict[str, list[str]] = defaultdict(list)
            for edge in edges:
                adjacency[edge.get("source")].append(edge.get("target"))
            while stack:
                current = stack.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                stack.extend(adjacency.get(current, []))
            check(reachable == set(ids), f"{name} has unreachable nodes: {sorted(set(ids) - reachable)}")
        max_runs = workflow.get("max_concurrent_runs")
        check(max_runs is None or (isinstance(max_runs, int) and max_runs > 0), f"{name} max_concurrent_runs must be positive")


def verify_schedules() -> None:
    schedules = ROOT / "schedules"
    expected = {"settlement-cycle", "settlement-approval"}
    found = {path.name for path in schedules.iterdir() if path.is_dir()}
    check(found == expected, f"schedules/ must contain {sorted(expected)}, found {sorted(found)}")
    workflows = {path.name for path in (ROOT / "workflows").iterdir() if path.is_dir()}
    tables = {path.name for path in (ROOT / "tables").iterdir() if path.is_dir()}
    for name in sorted(expected):
        path = schedules / name / f"{name}.json"
        check(path.exists(), f"missing {rel(path)}")
        if not path.exists():
            continue
        schedule = load_json(path)
        check(schedule.get("name") == name, f"{rel(path)} name must be {name}")
        check(schedule.get("workflow_name") in workflows, f"{name} points at an unknown workflow")
        check(schedule.get("is_active") is True, f"{name} must be active on import")
        schedule_type = schedule.get("schedule_type")
        config = schedule.get("config", {})
        if schedule_type == "TIME":
            check("cron" in config, f"{name} needs a cron expression")
            check("timezone" in config, f"{name} needs a timezone")
            check(config.get("max_concurrent_runs") == 1, f"{name} must cap concurrent runs at one")
        elif schedule_type == "DATASTORE":
            check(config.get("table_name") in tables, f"{name} triggers on an unknown table")
            operations = config.get("operations", [])
            check(bool(operations), f"{name} needs trigger operations")
            check(set(operations) <= {"INSERT", "UPDATE", "DELETE"}, f"{name} has an invalid operation")
        else:
            failures.append(f"{name} has an invalid schedule_type {schedule_type!r}")
            checks += 1


def verify_app() -> None:
    path = ROOT / "apps" / "settlement-desk"
    manifest_path = path / "settlement-desk.json"
    html_path = path / "html.html"
    check(manifest_path.exists(), f"missing {rel(manifest_path)}")
    check(html_path.exists(), f"missing {rel(html_path)}")
    if not manifest_path.exists() or not html_path.exists():
        return
    manifest = load_json(manifest_path)
    check(manifest.get("name") == "settlement-desk", "app name must be settlement-desk")
    check(bool(manifest.get("description")), "app needs a description")
    check(manifest.get("public_slug") == "settlement-desk", "app public_slug must be settlement-desk")
    html = html_path.read_text(encoding="utf-8")
    check("/public/sdk/lemma-client.js" in html, "app must load the browser SDK from apiUrl")
    check("pod-client.js" not in html, "app must not load the retired SDK")
    check("submitForm" in html, "app must submit the waiting workflow form")
    check("active_wait" in html, "app must read the active wait")
    check("approver_email" in html, "app must pass the approver email through the form")
    check("records.listAll" in html, "app must page reads that need a complete month")
    check("html.html" in {p.name for p in path.iterdir()}, "app source must be html.html")


def verify_settlement_math_module() -> None:
    try:
        from settlement_math import percent_of
    except ImportError as exc:
        failures.append(f"cannot import tools/settlement_math.py: {exc}")
        return
    check(percent_of(2_845_00, 7_000) == 199_150, "percent_of(284500, 7000) must be 199150")
    check(percent_of(1, 5_000) == 1, "half-up rounding must round 0.5 cent up")
    check(percent_of(0, 7_000) == 0, "percent_of(0) must be zero")


def _is_int(value: str) -> bool:
    try:
        int(value)
        return True
    except ValueError:
        return False


def _is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _is_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def main() -> int:
    verify_pod()
    verify_ascii()
    tables = verify_tables()
    verify_seed(tables)
    verify_files()
    verify_functions()
    verify_agent()
    verify_workflows()
    verify_schedules()
    verify_app()
    verify_settlement_math_module()

    if failures:
        print(f"FAIL: {len(failures)} problem(s) in {checks} checks")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"OK: {checks} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
