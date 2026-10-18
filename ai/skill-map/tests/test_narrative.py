import json
import re

from skill_map.build import build
from skill_map.config import load_config

NARRATIVE = """\
<!-- explains data-key="IN-A-COMMENT" and <section data-slot="chain">x</section> -->
<section data-slot="ablauf"><h2>Ein Vorhaben</h2><p>Erst <code data-key="superp:brainstorming">brainstorming</code>,
dann <code data-key="superp:gone-skill">weg</code>.</p></section>
<section data-slot="auffaellig"><h2>Was auffällt</h2><p>MARK-AUFFAELLIG
<code data-key="plain" data-copy="/plain --flag">plain</code></p></section>
<template data-lane-note="personal-commands">Notiz <b>fett</b></template>
<template data-lane-note="no-such-place">weg</template>
<script type="application/json" data-kurz>{"superp:tdd": "erst roter Test", "nokey": "x"}</script>
"""


def run(tmp_path, narrative=None):
    if narrative is not None:
        p = tmp_path / "erz.html"
        p.write_text(narrative, encoding="utf-8")
        cfg = load_config()
        cfg.narrative = p
    else:
        cfg = load_config()
    lines = []
    out = build(cfg, tmp_path / "out", lines.append)
    return out, lines


def test_slots_are_filled_and_markers_gone(world, tmp_path):
    out, _ = run(tmp_path, NARRATIVE)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "MARK-AUFFAELLIG" in html and "<h2>Ein Vorhaben</h2>" in html
    assert "<!-- slot:ablauf -->" not in html and "<!-- slot:auffaellig -->" not in html
    assert html.index("Ein Vorhaben") < html.index("MARK-AUFFAELLIG")
    data = json.loads(re.search(r'<script type="application/json" id="narrative">(.*?)</script>', html, re.S).group(1))
    assert data["lane_notes"]["personal-commands"] == "Notiz <b>fett</b>"
    assert data["kurz"]["superp:tdd"] == "erst roter Test"


def test_missing_references_are_reported(world, tmp_path):
    out, lines = run(tmp_path, NARRATIVE)
    inv = json.loads((out / "inventory.json").read_text(encoding="utf-8"))
    assert inv["narrative"]["missing_keys"] == ["no-such-place", "nokey", "superp:gone-skill"]
    assert any("3 references to missing entries" in line and "superp:gone-skill" in line for line in lines)


def test_without_narrative_file_the_build_works(world, tmp_path):
    cfg = load_config()
    cfg.narrative = tmp_path / "does-not-exist.html"
    out = build(cfg, tmp_path / "out", lambda _: None)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "data-slot" not in html and "<!-- slot:" not in html
    assert json.loads((out / "inventory.json").read_text())["narrative"]["missing_keys"] == []


def test_title_is_set(world, tmp_path, conf):
    from world import CONFIG
    conf('title = "Meine <Karte>"\n' + CONFIG)
    out, _ = run(tmp_path)
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "<title>Meine &lt;Karte&gt;</title>" in html


def test_self_contained_page_embeds_both_files(world, tmp_path):
    out, _ = run(tmp_path, NARRATIVE)
    page = (out / "skill-map.html").read_text(encoding="utf-8")
    for sid, name in (("inventory-data", "inventory.json"), ("wortlaut-data", "wortlaut.json")):
        m = re.search(rf'<script type="application/json" id="{sid}">(.*?)</script>', page, re.S)
        assert json.loads(m.group(1)) == json.loads((out / name).read_text(encoding="utf-8"))
    # the fixture text "</script><b>no</b>" must not end a script block early
    opened = len(re.findall(r"<script\b", page))
    assert page.count("</script>") == opened
    index = (out / "index.html").read_text(encoding="utf-8")
    assert 'id="inventory-data"' not in index           # index.html fetches the files
