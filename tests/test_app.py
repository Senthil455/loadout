from __future__ import annotations

import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTML_PATH = ROOT / "apps" / "settlement-desk" / "html.html"


class InlineScripts(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_script = False
        self.has_src = False
        self.current: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        self.in_script = True
        self.has_src = any(name == "src" and value for name, value in attrs)
        self.current = []

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.current.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_script:
            if not self.has_src and "".join(self.current).strip():
                self.scripts.append("".join(self.current))
            self.in_script = False
            self.has_src = False
            self.current = []


def scripts() -> list[str]:
    parser = InlineScripts()
    parser.feed(HTML_PATH.read_text(encoding="utf-8"))
    return parser.scripts


def test_app_has_inline_javascript() -> None:
    assert len(scripts()) >= 1


def test_inline_javascript_parses() -> None:
    node = subprocess.run(["node", "--version"], capture_output=True, text=True, check=False)
    if node.returncode != 0:
        pytest.skip("node is not available")
    with tempfile.TemporaryDirectory() as folder:
        for index, source in enumerate(scripts()):
            path = Path(folder) / f"script-{index}.js"
            path.write_text(source, encoding="utf-8")
            result = subprocess.run(
                ["node", "--check", str(path)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stderr


def test_app_shows_the_workflow_states() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    for phrase in (
        "Run settlement cycle",
        "Needs you",
        "In review",
        "Ready to pay",
        "Settled",
        "Record payment",
        "Reopen review",
        "Needs a decision",
    ):
        assert phrase in html, phrase


def test_app_submits_the_form_instead_of_calling_the_recorder() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "submitForm" in html
    assert "active_wait" in html
    assert "node_id: run.wait.node_id" in html
    assert "approver_email" in html
    assert 'client.functions.run("record_review"' not in html


def test_app_claims_the_desk_with_a_pod_member_id() -> None:
    html = HTML_PATH.read_text(encoding="utf-8")
    assert "approval_member_id" in html
    assert "currentPodMemberId" in html
    assert "pod_member_id" in html


def test_app_is_ascii_only() -> None:
    body = HTML_PATH.read_text(encoding="utf-8")
    assert all(ord(char) < 128 for char in body)
