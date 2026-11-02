"""Arete -> Venato: an existing user's data folder, saved secrets, config and environment carry over."""

import importlib
import json

import pytest


def test_old_data_folder_is_copied_across_once(tmp_path, monkeypatch):
    from venato import system
    monkeypatch.delenv("VENATO_DATA_DIR", raising=False)
    monkeypatch.delenv("ARETE_DATA_DIR", raising=False)
    monkeypatch.setattr(system, "default_data_dir", lambda name="Venato": tmp_path / name)
    old = tmp_path / "Arete"
    (old / "backups").mkdir(parents=True)
    (old / "life.db").write_bytes(b"my data")
    (old / "settings.json").write_text('{"wizard_done": true}')
    new = system.data_dir()
    assert new == tmp_path / "Venato"
    assert (new / "life.db").read_bytes() == b"my data" and (new / "backups").is_dir()
    assert (old / "life.db").read_bytes() == b"my data"                # the old one is left as a backup
    (new / "life.db").write_bytes(b"newer")
    assert system.data_dir() == new and (new / "life.db").read_bytes() == b"newer"   # only copied once


def test_fresh_computer_and_env_overrides(tmp_path, monkeypatch):
    from venato import system
    monkeypatch.delenv("VENATO_DATA_DIR", raising=False)
    monkeypatch.setattr(system, "default_data_dir", lambda name="Venato": tmp_path / name)
    assert system.data_dir() == tmp_path / "Venato" and not (tmp_path / "Arete").exists()
    monkeypatch.setenv("ARETE_DATA_DIR", str(tmp_path / "custom"))      # an old setting still works
    assert system.data_dir() == tmp_path / "custom"
    monkeypatch.setenv("VENATO_DATA_DIR", str(tmp_path / "newer"))      # the new name wins
    assert system.data_dir() == tmp_path / "newer"
    monkeypatch.setenv("ARETE_CLAUDE_PATH", "/opt/claude")
    assert system.env("CLAUDE_PATH") == "/opt/claude"


def test_saved_secrets_move_to_the_new_name(store):
    from venato import assistant, outlook
    assistant.keyring.set_password("Arete", assistant.KEY_ACCOUNT, "sk-ant-old")
    outlook.keyring.set_password("Arete", outlook.KEYCHAIN_ACCOUNT, "https://outlook.office365.com/x.ics")
    assert assistant.api_key() == "sk-ant-old" and assistant.saved_api_key()
    assert assistant.keyring.get_password("Venato", assistant.KEY_ACCOUNT) == "sk-ant-old"     # copied over
    assert outlook.ics_url() == "https://outlook.office365.com/x.ics"
    assert outlook.keyring.get_password("Venato", outlook.KEYCHAIN_ACCOUNT)
    assistant.forget_api_key()                                          # removing it removes both copies
    assert assistant.api_key() is None


def test_old_config_file_still_read(store):
    from venato import assistant
    assistant = importlib.reload(assistant)
    (store.DATA_DIR / "arete_config.json").write_text(json.dumps({"model": "haiku"}))
    assert assistant.load_config() == {"model": "haiku"}
    (store.DATA_DIR / "venato_config.json").write_text(json.dumps({"model": "sonnet"}))
    assert assistant.load_config() == {"model": "sonnet"}
