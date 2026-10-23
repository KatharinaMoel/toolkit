import re
import subprocess
import sys
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent / "demo" / "make_demo.py"
# The demo is public: only invented people may appear in it.
INVENTED = {"alice", "bob", "carol", "dan"}


def test_demo_snapshot_renders(tmp_path):
    out = subprocess.run([sys.executable, "-I", str(DEMO), str(tmp_path)], capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    html = (tmp_path / "index.html").read_text()
    assert len(re.findall(r'<tr data-iid="\d+"', html)) == 6
    assert "yes (squashed)" in html and "Approval ready" in html
    pages = list((tmp_path / "mr").glob("*.html"))
    assert len(pages) == 6
    assert any("<h2>Changes" in p.read_text() for p in pages)


def test_demo_contains_only_invented_people(tmp_path):
    subprocess.run([sys.executable, "-I", str(DEMO), str(tmp_path)], check=True, capture_output=True, timeout=60)
    text = "\n".join(p.read_text(errors="replace")
                     for p in tmp_path.rglob("*") if p.is_file() and p.suffix != ".png")
    usernames = set(re.findall(r'"username":\s*"([^"]*)"', text))
    assert usernames and usernames <= INVENTED, usernames - INVENTED
    assert "acme/garden-planner" in text
