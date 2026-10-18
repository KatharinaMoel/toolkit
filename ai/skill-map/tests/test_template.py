import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "page" / "template.html"
SLOTS = ("ablauf", "chain", "wofuer", "auffaellig", "repo-wissen")


def text():
    return TEMPLATE.read_text(encoding="utf-8")


def test_every_slot_marker_is_there():
    t = text()
    for slot in SLOTS:
        assert t.count(f"<!-- slot:{slot} -->") == 1
    assert t.count("<!-- data -->") == 1 and t.count("<!-- narrative -->") == 1


def test_no_entry_names_in_the_template():
    t = text()
    for name in ("brainstorming", "kios-start", "superpowers", "superp", "k-start", "pr-review-toolkit",
                 "my-private-project", "timesheet"):
        assert name not in t, name


def test_inner_html_only_in_the_narrative_function():
    t = text()
    assert t.count("innerHTML") == 1
    func = re.search(r"function insertNarrative\(.*?\n  \}", t, re.S).group(0)
    assert "innerHTML" in func


def test_design_rules_from_the_prototype():
    t = text()
    assert ':root:not([data-theme="light"])' in t and ':root[data-theme="dark"]' in t
    assert "prefers-reduced-motion" in t and "max-width:720px" in t and "max-width:640px" in t
    assert re.search(r"<script[^>]+src=", t) is None          # no external scripts


def test_narrative_links_skip_the_lookup_rows_and_the_viewer():
    func = re.search(r"function linkNarrative\(\)\{.*?\n  \}", text(), re.S).group(0)
    assert "item" in func and ".viewer" in func


def test_kinds_without_usage_counts_show_a_dash():
    func = re.search(r"function useCell\(e\)\{.*?\n  \}", text(), re.S).group(0)
    assert "COUNTED" in func and "–" in func
