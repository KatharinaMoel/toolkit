import subprocess
from io import StringIO

from mr_export import browser
from mr_export.runner import Console, Runner

PERMS_NO_HOME = "[Context]\nfilesystems=host-etc;xdg-download;xdg-documents;~/.config/dconf:ro;\n"


class FakeTools:
    """Answers xdg-mime / flatpak / xdg-open from a table and records the calls."""

    def __init__(self, default="com.google.Chrome.desktop", flatpak=True, perms=PERMS_NO_HOME):
        self.default, self.flatpak, self.perms = default, flatpak, perms
        self.calls: list[list[str]] = []

    def __call__(self, cmd, cwd=None, capture_output=True, timeout=None):
        self.calls.append(list(cmd))
        out, rc = "", 0
        if cmd[:2] == ["xdg-mime", "query"]:
            out = self.default + "\n"
        elif cmd[:2] == ["flatpak", "info"] and "--show-permissions" in cmd:
            out, rc = (self.perms, 0) if self.flatpak else ("", 1)
        elif cmd[:2] == ["flatpak", "info"]:
            rc = 0 if self.flatpak else 1
        return subprocess.CompletedProcess(cmd, rc, out.encode(), b"")


def runner(tools, tmp_path):
    return Runner(tmp_path, Console(StringIO()), run=tools)


def test_flatpak_without_access_is_detected(tmp_path, home):
    path = home / "mr-export" / "app" / "latest" / "index.html"
    assert browser.flatpak_without_access(runner(FakeTools(), tmp_path), path) == "com.google.Chrome"


def test_flatpak_with_home_access_is_fine(tmp_path, home):
    tools = FakeTools(perms="[Context]\nfilesystems=home;\n")
    assert browser.flatpak_without_access(runner(tools, tmp_path), home / "x" / "index.html") is None


def test_flatpak_with_access_to_the_folder_is_fine(tmp_path, home):
    tools = FakeTools(perms="[Context]\nfilesystems=~/mr-export:ro;\n")
    assert browser.flatpak_without_access(runner(tools, tmp_path), home / "mr-export" / "a" / "i.html") is None


def test_regular_browser_is_fine(tmp_path, home):
    tools = FakeTools(default="firefox.desktop", flatpak=False)
    assert browser.flatpak_without_access(runner(tools, tmp_path), home / "x.html") is None


def test_override_command():
    assert (browser.override_command("com.google.Chrome", "/home/u/mr-export")
            == "flatpak override --user --filesystem=/home/u/mr-export:ro com.google.Chrome")
