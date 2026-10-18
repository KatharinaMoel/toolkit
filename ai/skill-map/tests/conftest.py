"""Test setup: the package under src/ is importable, every test runs in a throwaway
HOME with its own XDG folders, and any network access fails the test."""
import socket
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

LAUNCHER = Path(__file__).resolve().parent.parent / "skill-map"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("skill-map must never open a network connection")
    monkeypatch.setattr(socket, "socket", refuse)


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fresh HOME with XDG config and state folders; returns the HOME path."""
    h = tmp_path / "home"
    (h / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(h / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(h / ".local" / "state"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return h


@pytest.fixture
def conf(home):
    """Write the config file: conf('vault = "~/notes"') -> its path."""
    def write(text: str) -> Path:
        p = home / ".config" / "skill-map" / "skill-map.conf"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p
    return write
