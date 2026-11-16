"""Platform differences (venato/system.py and the Claude CLI search), faked for each system."""

import os
from pathlib import Path

import pytest

from venato import system


def as_system(monkeypatch, name):
    monkeypatch.setattr(system, "IS_MAC", name == "mac")
    monkeypatch.setattr(system, "IS_WINDOWS", name == "windows")


def test_data_folder_per_system(monkeypatch, tmp_path):
    as_system(monkeypatch, "mac")
    assert system.default_data_dir() == Path.home() / "Library" / "Application Support" / "Venato"
    as_system(monkeypatch, "windows")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert system.default_data_dir() == tmp_path / "Roaming" / "Venato"
    monkeypatch.delenv("APPDATA")
    assert system.default_data_dir() == Path.home() / "AppData" / "Roaming" / "Venato"
    as_system(monkeypatch, "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    assert system.default_data_dir() == tmp_path / "share" / "Venato"


def test_open_folder(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(system.subprocess, "run", lambda args, check: calls.append(args))
    as_system(monkeypatch, "mac")
    system.open_folder(tmp_path / "new")
    assert (tmp_path / "new").is_dir() and calls[-1] == ["open", str(tmp_path / "new")]
    as_system(monkeypatch, "linux")
    system.open_folder(tmp_path)
    assert calls[-1][0] == "xdg-open"
    as_system(monkeypatch, "windows")
    monkeypatch.setattr(system.os, "startfile", lambda p: calls.append(["startfile", str(p)]), raising=False)
    system.open_folder(tmp_path)
    assert calls[-1] == ["startfile", str(tmp_path)]


def test_claude_env_paths(monkeypatch, store):
    from venato import assistant
    monkeypatch.setenv("PATH", "/usr/bin")
    as_system(monkeypatch, "mac")
    env = assistant._env("/somewhere/claude")
    first, second = env["PATH"].split(os.pathsep)[:2]
    assert first == str(Path("/somewhere/claude").parent) and second == "/opt/homebrew/bin"
    assert "USERPROFILE" not in env
    as_system(monkeypatch, "windows")
    env = assistant._env(str(Path("C:/Users/x/.local/bin/claude.exe")))
    assert "/opt/homebrew/bin" not in env["PATH"] and env["USERPROFILE"]


class FakeKeyring:
    def __init__(self, **saved):
        self.saved = {tuple(key.split("|")): value for key, value in saved.items()}

    def get_password(self, service, account):
        return self.saved.get((service, account))

    def set_password(self, service, account, value):
        self.saved[(service, account)] = value

    def delete_password(self, service, account):
        del self.saved[(service, account)]


@pytest.fixture
def old_install(tmp_path, monkeypatch):
    monkeypatch.delenv("VENATO_DATA_DIR", raising=False)
    monkeypatch.delenv("ARETE_DATA_DIR", raising=False)
    monkeypatch.setattr(system, "default_data_dir", lambda name="Venato": tmp_path / name)
    monkeypatch.setattr(system, "_migrated", False)
    old = tmp_path / "Arete"
    old.mkdir()
    (old / "life.db").write_text("my data")
    return tmp_path


def test_migration_moves_data_and_secrets(old_install, monkeypatch):
    fake = FakeKeyring(**{"Arete|outlook-ics-url": "https://cal"})
    monkeypatch.setattr(system, "keyring", fake)
    system.migrate_from_old_name()
    assert (old_install / "Venato" / "life.db").read_text() == "my data"
    assert (old_install / "Arete" / "life.db").exists()                  # left as a backup
    assert fake.saved == {("Venato", "outlook-ics-url"): "https://cal", ("Arete", "outlook-ics-url"): "https://cal"}


def test_migration_from_veneto_comes_first(old_install, monkeypatch):
    fake = FakeKeyring(**{"Veneto|strava-tokens": "tok"})
    monkeypatch.setattr(system, "keyring", fake)
    (old_install / "Veneto").mkdir()
    (old_install / "Veneto" / "life.db").write_text("newest data")
    system.migrate_from_old_name()
    assert (old_install / "Venato" / "life.db").read_text() == "newest data"
    assert fake.saved == {("Venato", "strava-tokens"): "tok", ("Veneto", "strava-tokens"): "tok"}   # old copy kept


def test_migration_never_replaces_existing_data(old_install, monkeypatch):
    fake = FakeKeyring(**{"Arete|outlook-ics-url": "https://old"})
    monkeypatch.setattr(system, "keyring", fake)
    (old_install / "Venato").mkdir()
    (old_install / "Venato" / "life.db").write_text("newer data")
    system.migrate_from_old_name()
    assert (old_install / "Venato" / "life.db").read_text() == "newer data"
    assert (old_install / "Arete" / "life.db").read_text() == "my data"
    assert fake.saved[("Venato", "outlook-ics-url")] == "https://old"   # no key there yet: brought across


def test_migration_skipped_for_tests_and_demo(old_install, monkeypatch):
    monkeypatch.setattr(system, "keyring", FakeKeyring())
    monkeypatch.setenv("VENATO_DATA_DIR", str(old_install / "elsewhere"))
    system.migrate_from_old_name()
    assert (old_install / "Arete" / "life.db").exists()
