from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def node(workflow: dict, node_id: str) -> dict:
    return next(item for item in workflow["nodes"] if item["id"] == node_id)


def test_approval_workflow_starts_from_the_review_request_insert() -> None:
    workflow = load("workflows/settlement-approval/settlement-approval.json")
    schedule = load("schedules/settlement-approval/settlement-approval.json")
    assert workflow["start"] == {
        "type": "DATASTORE_EVENT",
        "config": {"table_name": "review_requests", "operations": ["INSERT"]},
    }
    assert schedule["schedule_type"] == "DATASTORE"
    assert schedule["config"]["table_name"] == "review_requests"
    assert schedule["config"]["operations"] == ["INSERT"]


def test_approval_workflow_uses_both_form_paths_and_ends_each_one() -> None:
    workflow = load("workflows/settlement-approval/settlement-approval.json")
    assigned = node(workflow, "approval_assigned")
    unassigned = node(workflow, "approval_open")
    assert assigned["config"]["assignee_pod_member_id_expression"] == "attach.approval_member_id"
    assert "assignee_pod_member_id_expression" not in unassigned["config"]
    for form in (assigned, unassigned):
        properties = form["config"]["input_schema"]["properties"]
        assert set(form["config"]["input_schema"]["required"]) == {"decision", "approved_payout_cents"}
        assert properties["decision"]["enum"] == ["approve", "hold"]
        assert properties["approved_payout_cents"]["type"] == "integer"
        assert properties["approver_email"]["type"] == "string"
    targets = {edge["target"] for edge in workflow["edges"] if edge["source"] == "route_assignee"}
    assert targets == {"approval_assigned", "approval_open"}


def test_approval_workflow_builds_the_packet_before_the_agent_runs() -> None:
    workflow = load("workflows/settlement-approval/settlement-approval.json")
    packet = node(workflow, "build_packet")
    review = node(workflow, "review")
    assert packet["type"] == "FUNCTION"
    assert packet["config"]["function_name"] == "build_review_packet"
    assert review["config"]["input_mapping"]["packet"] == {
        "type": "expression",
        "value": "build_packet.packet",
    }
    assert any(
        edge["source"] == "build_packet" and edge["target"] == "review"
        for edge in workflow["edges"]
    )


def test_reviewer_reads_only_the_packet_and_holds_no_grants() -> None:
    manifest = load("agents/settlement-reviewer/settlement-reviewer.json")
    assert manifest["toolsets"] == []
    assert manifest["permissions"]["grants"] == []
    assert "packet" in manifest["input_schema"]["required"]
    assert manifest["input_schema"]["properties"]["packet"]["type"] == "object"


def test_approval_workflow_carries_the_submitter_into_every_record_call() -> None:
    workflow = load("workflows/settlement-approval/settlement-approval.json")
    record_nodes = [
        item for item in workflow["nodes"]
        if item["type"] == "FUNCTION" and item["config"]["function_name"] == "record_review"
    ]
    assert len(record_nodes) == 4
    for item in record_nodes:
        mapping = item["config"]["input_mapping"]
        assert mapping["decided_by"]["value"].endswith(".approver_email")
        assert mapping["decided_by"].get("optional") is True
        assert mapping["approved"]["type"] == "literal"


def test_decision_nodes_have_a_default_route() -> None:
    workflow = load("workflows/settlement-approval/settlement-approval.json")
    edges = workflow["edges"]
    for item in workflow["nodes"]:
        if item["type"] != "DECISION":
            continue
        rule_targets = {
            rule["next_node_id"]
            for rule in item["config"].get("rules", [])
        }
        default_targets = {
            edge["target"] for edge in edges
            if edge["source"] == item["id"] and edge["target"] not in rule_targets
        }
        assert default_targets, item["id"]


def test_cycle_is_scheduled_once_and_capped() -> None:
    workflow = load("workflows/settlement-cycle/settlement-cycle.json")
    schedule = load("schedules/settlement-cycle/settlement-cycle.json")
    assert workflow["start"]["type"] == "SCHEDULED"
    assert workflow["max_concurrent_runs"] == 1
    assert schedule["config"]["cron"] == "0 9 * * *"
    assert schedule["config"]["timezone"] == "America/New_York"
    assert schedule["config"]["max_concurrent_runs"] == 1
    assert node(workflow, "prepare")["config"]["function_name"] == "prepare_settlements"


def test_reviewer_instruction_lists_every_check_in_order() -> None:
    instruction = (ROOT / "agents/settlement-reviewer/instruction.md").read_text(encoding="utf-8")
    checks = instruction.split("## The checks", 1)[1].split("## How to decide", 1)[0]
    positions = [
        checks.index(check_id)
        for check_id in (
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
        )
    ]
    assert positions == sorted(positions)


def test_every_function_and_agent_referenced_by_a_workflow_exists() -> None:
    for name in ("settlement-cycle", "settlement-approval"):
        workflow = load(f"workflows/{name}/{name}.json")
        for item in workflow["nodes"]:
            if item["type"] == "FUNCTION":
                function_name = item["config"]["function_name"]
                assert (ROOT / "functions" / function_name / f"{function_name}.json").exists()
            if item["type"] == "AGENT":
                agent_name = item["config"]["agent_name"]
                assert (ROOT / "agents" / agent_name / f"{agent_name}.json").exists()
