"""The user's narrative: her own HTML fragments, merged into the page at build time.

The file lives outside the repository (it is personal). It may hold
  <section data-slot="NAME"> … </section>             placed at <!-- slot:NAME --> in the template
  <template data-lane-note="PLACE-ID"> … </template>  a note under a lane
  <script type="application/json" data-kurz>{…}</script>   short descriptions by key
and refers to entries with data-key="KEY". Sections must not nest. The narrative is
trusted and inserted as HTML; everything from the data is inserted as text."""
import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SLOTS = ("ablauf", "chain", "wofuer", "auffaellig", "repo-wissen")
_SLOT = re.compile(r'<section\b[^>]*\bdata-slot="([A-Za-z0-9_-]+)"[^>]*>.*?</section>', re.S)
_NOTE = re.compile(r'<template\b[^>]*\bdata-lane-note="([^"]+)"[^>]*>(.*?)</template>', re.S)
_KURZ = re.compile(r'<script\b[^>]*\bdata-kurz\b[^>]*>(.*?)</script>', re.S)
_KEY = re.compile(r'\bdata-key="([^"]+)"')
_COMMENT = re.compile(r"<!--.*?-->", re.S)


@dataclass
class Narrative:
    slots: dict[str, str] = field(default_factory=dict)
    lane_notes: dict[str, str] = field(default_factory=dict)
    kurz: dict[str, str] = field(default_factory=dict)
    keys: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)


def read_narrative(path: Path) -> Narrative:
    """An empty narrative when the file does not exist."""
    n = Narrative()
    if not path.is_file():
        return n
    text = _COMMENT.sub("", path.read_text(encoding="utf-8"))   # comments explain, they do not count
    for m in _SLOT.finditer(text):
        if m.group(1) in SLOTS:
            n.slots[m.group(1)] = m.group(0)
        else:
            n.notes.append(f"narrative: unknown slot {m.group(1)} - not shown")
    n.lane_notes = {m.group(1): m.group(2).strip() for m in _NOTE.finditer(text)}
    for m in _KURZ.finditer(text):
        try:
            kurz = json.loads(m.group(1))
        except ValueError:
            n.notes.append("narrative: data-kurz is not valid JSON - ignored")
            continue
        if isinstance(kurz, dict):
            n.kurz.update({str(k): str(v) for k, v in kurz.items()})
    n.keys = set(_KEY.findall(text))
    return n


def missing_keys(n: Narrative, entries: set[str], places: set[str]) -> list[str]:
    return sorted((n.keys - entries) | (set(n.lane_notes) - places) | (set(n.kurz) - entries))


def script_json(data) -> str:
    """JSON that can sit inside <script>: "</" can never end the block early."""
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def render_page(template: str, title: str, n: Narrative, embedded: tuple[dict, dict] | None) -> str:
    page = template.replace("<!-- title -->", html.escape(title), 1)
    for slot in SLOTS:
        page = page.replace(f"<!-- slot:{slot} -->", n.slots.get(slot, ""), 1)
    page = page.replace("<!-- narrative -->", '<script type="application/json" id="narrative">'
                        + script_json({"lane_notes": n.lane_notes, "kurz": n.kurz}) + "</script>", 1)
    data = ""
    if embedded is not None:
        inventory, wortlaut = embedded
        data = ('<script type="application/json" id="inventory-data">' + script_json(inventory) + "</script>\n"
                '<script type="application/json" id="wortlaut-data">' + script_json(wortlaut) + "</script>")
    return page.replace("<!-- data -->", data, 1)
