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
