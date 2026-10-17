import subprocess
import sys
from pathlib import Path

from notebokki import config

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_default_session_path_is_outside_the_repository(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    session = config.session_path().resolve()
    assert not session.is_relative_to(REPO_ROOT)


def test_xdg_config_home_redirects_registry_and_session(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config.registry_path() == tmp_path / "xdg" / "notebokki" / "registry.json"
    assert config.session_path().is_relative_to(tmp_path / "xdg" / "notebokki")


def test_default_falls_back_to_dot_config_under_home(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert config.config_dir() == tmp_path / ".config" / "notebokki"


def test_explicit_override_beats_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    reg = tmp_path / "elsewhere" / "reg.json"
    ses = tmp_path / "other" / "s" / "state.json"
    assert config.registry_path(reg) == reg
    assert config.session_path(ses) == ses


def test_registry_and_session_are_distinct_and_session_has_its_own_directory(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    reg, ses = config.registry_path(), config.session_path()
    assert reg != ses
    assert ses.parent != reg.parent
    assert ses.parent.parent == reg.parent


def test_console_script_help_lists_setup_and_serve():
    out = subprocess.run(
        [sys.executable, "-m", "notebokki", "--help"], capture_output=True, text=True, check=True
    ).stdout
    assert "setup" in out
    assert "serve" in out
