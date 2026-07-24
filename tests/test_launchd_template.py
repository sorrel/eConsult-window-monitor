from pathlib import Path

PLIST = Path(__file__).parent.parent / "launchd" / "com.econsult.window-monitor.plist"


def test_plist_uses_placeholders_not_machine_paths():
    text = PLIST.read_text(encoding="utf-8")
    assert "__REPO_DIR__" in text
    # No real user home path may be committed.
    assert "/Users/" not in text


def test_plist_runs_venv_python_not_uv_at_runtime():
    # The agent runs the project's venv Python directly so a locked-down launchd
    # context cannot hang uv at runtime.
    text = PLIST.read_text(encoding="utf-8")
    assert "__REPO_DIR__/.venv/bin/python" in text
    assert "run</string>" not in text  # not "uv run ..."


def test_plist_declares_keepalive_and_runatload():
    text = PLIST.read_text(encoding="utf-8")
    assert "com.econsult.window-monitor" in text
    assert "KeepAlive" in text
    assert "RunAtLoad" in text
    assert "monitor.daemon" in text
