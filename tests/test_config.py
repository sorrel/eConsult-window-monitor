from pathlib import Path
from monitor import config


def test_paths_are_runtime_derived_and_anchored_under_repo_root():
    # REPO_ROOT is derived from the package location, not a hardcoded home path.
    # Under the src layout the package lives at src/monitor/, so the repo root is
    # three parents up from config.py (config.py -> monitor -> src -> repo root).
    expected_root = Path(config.__file__).resolve().parent.parent.parent
    assert config.REPO_ROOT == expected_root
    assert config.REPO_ROOT.is_absolute()
    # Guard against the src-layout regression: data must live at repo-root/data,
    # never inside src/.
    assert config.DATA_DIR == config.REPO_ROOT / "data"
    assert "src" not in config.DATA_DIR.relative_to(config.REPO_ROOT).parts
    # Every data path is a descendant of REPO_ROOT (so a hardcoded absolute path
    # pointing elsewhere would fail this).
    assert config.LOG_PATH == config.DATA_DIR / "observations.jsonl"
    assert config.SNAPSHOT_DIR == config.DATA_DIR / "snapshots"
    for p in (config.DATA_DIR, config.LOG_PATH, config.SNAPSHOT_DIR):
        assert config.REPO_ROOT in p.parents


def test_user_agent_has_no_email():
    assert "@" not in config.USER_AGENT
    assert config.USER_AGENT.startswith("econsult-window-monitor/")


def test_cadence_values():
    assert config.DENSE_START == "05:30"
    assert config.DENSE_END == "10:00"
    assert config.DENSE_INTERVAL == 20
    assert config.BACKGROUND_INTERVAL == 1200
    assert config.ADMIN_INTERVAL == 1200
    assert config.CLINICAL_PATH == "/"
    assert config.ADMIN_PATH == "/admin"


# --- .env / 1Password local-env file loading -------------------------------
#
# The secrets file is normally a FIFO mounted by 1Password, which yields its
# contents only once 1Password attaches as a writer. These tests cover both
# shapes and, crucially, the case where no writer ever comes: config is
# imported by the CLI and the tests, so a blocking read there would hang
# everything.

import os
import threading
import time

import pytest

from monitor import config as config_mod


def _write_fifo(path, text, delay=0.0):
    """Attach as a writer to `path` after `delay`, like 1Password does."""
    def _writer():
        if delay:
            time.sleep(delay)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    thread = threading.Thread(target=_writer, daemon=True)
    thread.start()
    return thread


def test_parse_env_handles_comments_quotes_and_export():
    parsed = config_mod._parse_env(
        "\n".join([
            "# a comment",
            "",
            "PLAIN=one",
            'QUOTED="two"',
            "SINGLE='three'",
            "export EXPORTED=four",
            "  SPACED  =  five  ",
            "NOT_A_PAIR",
        ])
    )
    assert parsed == {
        "PLAIN": "one",
        "QUOTED": "two",
        "SINGLE": "three",
        "EXPORTED": "four",
        "SPACED": "five",
    }


def test_read_env_file_reads_a_regular_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text("ECONSULT_BASE_URL=https://example.test\n", encoding="utf-8")
    # Compare the parsed value exactly rather than substring-matching the raw
    # text: a URL that merely *contains* the expected one proves nothing.
    parsed = config_mod._parse_env(config_mod._read_env_file(path))
    assert parsed["ECONSULT_BASE_URL"] == "https://example.test"


def test_read_env_file_returns_empty_when_absent(tmp_path):
    assert config_mod._read_env_file(tmp_path / "nope.env") == ""


def test_read_env_file_reads_a_fifo_once_a_writer_attaches(tmp_path):
    path = tmp_path / ".env"
    os.mkfifo(path)
    _write_fifo(path, "ECONSULT_BASE_URL=https://fifo.test\n", delay=0.2)
    text = config_mod._read_env_file(path, timeout=5.0)
    assert config_mod._parse_env(text)["ECONSULT_BASE_URL"] == "https://fifo.test"


def test_read_env_file_gives_up_on_a_fifo_with_no_writer(tmp_path):
    """The locked-1Password case: must time out, not hang forever."""
    path = tmp_path / ".env"
    os.mkfifo(path)
    started = time.monotonic()
    assert config_mod._read_env_file(path, timeout=0.3) == ""
    assert time.monotonic() - started < 3.0


def test_base_url_precedence_env_beats_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ECONSULT_BASE_URL=https://from-file.test\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ENV_FILE", env_file)
    monkeypatch.setenv("ECONSULT_BASE_URL", "https://from-env.test/")
    assert config_mod._resolve_base_url() == "https://from-env.test"


def test_base_url_falls_back_from_env_file_to_local_file(tmp_path, monkeypatch):
    local = tmp_path / "target_url.local"
    local.write_text("https://from-local.test/\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ENV_FILE", tmp_path / "absent.env")
    monkeypatch.setattr(config_mod, "_LOCAL_URL_FILE", local)
    monkeypatch.delenv("ECONSULT_BASE_URL", raising=False)
    assert config_mod._resolve_base_url() == "https://from-local.test"


def test_env_file_beats_local_file(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ECONSULT_BASE_URL=https://from-file.test\n", encoding="utf-8")
    local = tmp_path / "target_url.local"
    local.write_text("https://from-local.test\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ENV_FILE", env_file)
    monkeypatch.setattr(config_mod, "_LOCAL_URL_FILE", local)
    monkeypatch.delenv("ECONSULT_BASE_URL", raising=False)
    assert config_mod._resolve_base_url() == "https://from-file.test"


def test_base_url_falls_back_to_placeholder_when_nothing_is_set(tmp_path, monkeypatch):
    monkeypatch.setattr(config_mod, "_ENV_FILE", tmp_path / "absent.env")
    monkeypatch.setattr(config_mod, "_LOCAL_URL_FILE", tmp_path / "absent.local")
    monkeypatch.delenv("ECONSULT_BASE_URL", raising=False)
    assert config_mod._resolve_base_url() == config_mod._PLACEHOLDER_URL


def test_require_configured_is_silent_when_configured(monkeypatch):
    monkeypatch.setattr(config_mod, "IS_CONFIGURED", True)
    config_mod.require_configured()  # must not raise


def test_require_configured_aborts_on_the_placeholder(monkeypatch):
    monkeypatch.setattr(config_mod, "IS_CONFIGURED", False)
    with pytest.raises(SystemExit) as excinfo:
        config_mod.require_configured()
    assert "no target URL configured" in str(excinfo.value)
