"""Tests for `--resume latest` and `--in DIR` launch sugar.

`hermes --tui --resume latest --in ./dir` (and the classic-CLI equivalents)
resolve "latest" through the same workspace-scoped MRU lookup as `-c`, with
`--in` re-homing the process before any session resolution happens.
"""

from __future__ import annotations

from argparse import Namespace

import pytest


def _args(**overrides):
    base = {
        "cli": False,
        "continue_last": None,
        "in_dir": None,
        "model": None,
        "no_restore_cwd": False,
        "provider": None,
        "query": None,
        "resume": None,
        "safe_mode": False,
        "toolsets": None,
        "tui": True,
        "tui_dev": False,
        "worktree": False,
    }
    base.update(overrides)
    return Namespace(**base)


@pytest.fixture
def main_mod(monkeypatch):
    import hermes_cli.main as mod

    monkeypatch.setattr(mod, "_has_any_provider_configured", lambda: True)
    monkeypatch.setattr(mod, "_sync_bundled_skills_for_startup", lambda: False)
    monkeypatch.setattr(mod, "_pin_kanban_board_env", lambda: None)
    return mod


@pytest.fixture
def launched(main_mod, monkeypatch):
    """Capture the _launch_tui call instead of exec'ing Node."""
    captured = {}

    def fake_launch(resume_session_id=None, **kwargs):
        captured["resume"] = resume_session_id
        captured.update(kwargs)
        raise SystemExit(0)

    monkeypatch.setattr(main_mod, "_launch_tui", fake_launch)
    return captured


# ---------------------------------------------------------------------------
# argparse surface
# ---------------------------------------------------------------------------


def test_top_level_parser_accepts_in_and_resume_latest():
    from hermes_cli._parser import build_top_level_parser

    parser, _subparsers, _chat = build_top_level_parser()
    args = parser.parse_args(["--tui", "--resume", "latest", "--in", "./dir"])
    assert args.tui is True
    assert args.resume == "latest"
    assert args.in_dir == "./dir"


def test_chat_subparser_accepts_in_flag():
    from hermes_cli._parser import build_top_level_parser

    parser, _subparsers, _chat = build_top_level_parser()
    args = parser.parse_args(["chat", "--in", "/tmp", "--resume", "latest"])
    assert args.in_dir == "/tmp"
    assert args.resume == "latest"


def test_top_level_in_value_not_mistaken_for_subcommand(monkeypatch):
    # `hermes --in chat` — "chat" is the flag's value, not the subcommand.
    import sys

    import hermes_cli.main as mod

    monkeypatch.setattr(sys, "argv", ["hermes", "--in", "chat", "--resume", "latest"])
    assert mod._first_positional_argv() is None


# ---------------------------------------------------------------------------
# --resume latest resolution
# ---------------------------------------------------------------------------


def test_resume_latest_resolves_to_mru_session(main_mod, launched, monkeypatch):
    monkeypatch.setattr(
        main_mod, "_resolve_last_session", lambda source="cli": "20260807_120000_abc123"
    )
    # Keyword must NOT fall through to title resolution.
    monkeypatch.setattr(
        main_mod,
        "_resolve_session_by_name_or_id",
        lambda val: val if val != "latest" else pytest.fail("'latest' hit title resolution"),
    )

    with pytest.raises(SystemExit) as exc:
        main_mod.cmd_chat(_args(resume="latest"))
    assert exc.value.code == 0
    assert launched["resume"] == "20260807_120000_abc123"


def test_resume_latest_tui_falls_back_to_cli_source(main_mod, launched, monkeypatch):
    calls = []

    def fake_resolve(source="cli"):
        calls.append(source)
        return "cli_session_1" if source == "cli" else None

    monkeypatch.setattr(main_mod, "_resolve_last_session", fake_resolve)
    monkeypatch.setattr(main_mod, "_resolve_session_by_name_or_id", lambda v: v)

    with pytest.raises(SystemExit) as exc:
        main_mod.cmd_chat(_args(resume="latest"))
    assert exc.value.code == 0
    assert calls == ["tui", "cli"]
    assert launched["resume"] == "cli_session_1"


def test_resume_latest_is_case_insensitive(main_mod, launched, monkeypatch):
    monkeypatch.setattr(main_mod, "_resolve_last_session", lambda source="cli": "sess_1")
    monkeypatch.setattr(main_mod, "_resolve_session_by_name_or_id", lambda v: v)

    with pytest.raises(SystemExit):
        main_mod.cmd_chat(_args(resume="Latest"))
    assert launched["resume"] == "sess_1"


def test_resume_latest_no_sessions_exits_with_error(main_mod, monkeypatch, capsys):
    monkeypatch.setattr(main_mod, "_resolve_last_session", lambda source="cli": None)

    with pytest.raises(SystemExit) as exc:
        main_mod.cmd_chat(_args(resume="latest"))
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "No previous TUI session found" in out


def test_resume_real_id_untouched_by_latest_keyword(main_mod, launched, monkeypatch):
    monkeypatch.setattr(
        main_mod,
        "_resolve_last_session",
        lambda source="cli": pytest.fail("MRU lookup must not run for explicit IDs"),
    )
    monkeypatch.setattr(main_mod, "_resolve_session_by_name_or_id", lambda v: v)

    with pytest.raises(SystemExit):
        main_mod.cmd_chat(_args(resume="20260807_120000_abc123"))
    assert launched["resume"] == "20260807_120000_abc123"


# ---------------------------------------------------------------------------
# --in DIR
# ---------------------------------------------------------------------------


def test_in_dir_chdirs_before_session_resolution(main_mod, launched, monkeypatch, tmp_path):
    import os

    target = tmp_path / "projdir"
    target.mkdir()
    start = os.getcwd()
    seen_cwd = {}

    def fake_resolve(source="cli"):
        seen_cwd["at_resolve"] = os.getcwd()
        return "sess_scoped"

    monkeypatch.setattr(main_mod, "_resolve_last_session", fake_resolve)
    monkeypatch.setattr(main_mod, "_resolve_session_by_name_or_id", lambda v: v)

    try:
        with pytest.raises(SystemExit):
            main_mod.cmd_chat(_args(resume="latest", in_dir=str(target)))
    finally:
        os.chdir(start)

    assert seen_cwd["at_resolve"] == str(target.resolve())
    assert launched["resume"] == "sess_scoped"


def test_in_dir_sets_no_restore_cwd(main_mod, launched, monkeypatch, tmp_path):
    import os

    target = tmp_path / "pin-here"
    target.mkdir()
    start = os.getcwd()

    args = _args(resume=None, in_dir=str(target))
    try:
        with pytest.raises(SystemExit):
            main_mod.cmd_chat(args)
    finally:
        os.chdir(start)

    assert args.no_restore_cwd is True


def test_in_dir_missing_directory_exits(main_mod, monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main_mod.cmd_chat(_args(in_dir=str(tmp_path / "nope")))
    assert exc.value.code == 1
    assert "--in directory not found" in capsys.readouterr().out


@pytest.mark.platforms("linux")
def test_in_dir_expands_user_home(main_mod, launched, monkeypatch, tmp_path):
    import os

    home = tmp_path / "home"
    (home / "proj").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    start = os.getcwd()

    try:
        with pytest.raises(SystemExit):
            main_mod.cmd_chat(_args(in_dir="~/proj"))
        assert os.getcwd() == str((home / "proj").resolve())
    finally:
        os.chdir(start)


# ---------------------------------------------------------------------------
# --in must win over an inherited TERMINAL_CWD (#106220)
# ---------------------------------------------------------------------------


def test_in_dir_replaces_inherited_terminal_cwd(main_mod, monkeypatch, tmp_path):
    """A parent Hermes surface, the shell or .env can export TERMINAL_CWD before
    the CLI starts. Every cwd consumer prefers that variable over the process
    cwd, so a bare chdir left the Codex app-server thread, the terminal tool and
    context-file discovery in the inherited directory."""
    import os
    from pathlib import Path

    from agent.runtime_cwd import resolve_agent_cwd

    inherited = tmp_path / "inherited"
    target = tmp_path / "target"
    inherited.mkdir()
    target.mkdir()
    monkeypatch.chdir(inherited)
    monkeypatch.setenv("TERMINAL_CWD", str(inherited))

    args = _args(in_dir=str(target))
    main_mod._apply_in_dir(args)

    assert Path.cwd().resolve() == target.resolve()
    assert Path(os.environ["TERMINAL_CWD"]).resolve() == target.resolve()
    assert resolve_agent_cwd().resolve() == target.resolve()
    assert args.no_restore_cwd is True


def test_in_dir_leaves_unset_terminal_cwd_unset(main_mod, monkeypatch, tmp_path):
    """Without an inherited value the backends already derive from the process
    cwd (local exports os.getcwd() at cli import, docker mounts it, the TUI
    child inherits the chdir). Pre-seeding a host path here would leak it into
    ssh/container backends that must keep their own default."""
    import os

    target = tmp_path / "target"
    target.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TERMINAL_CWD", raising=False)

    main_mod._apply_in_dir(_args(in_dir=str(target)))

    assert "TERMINAL_CWD" not in os.environ


@pytest.mark.parametrize("launch_name,in_name", [
    ("workspace", None), ("configured", None), ("configured", "workspace"),
])
def test_local_cli_cwd_survives_terminal_and_dotenv_bridges(
    tmp_path, monkeypatch, main_mod, launched, launch_name, in_name,
):
    """The launch resolver, both config bridges and project loader agree on cwd."""
    import os
    from hermes_cli.env_loader import load_hermes_dotenv
    from agent.runtime_cwd import resolve_context_cwd
    from agent.prompt_builder import build_context_files_prompt
    from tools import terminal_tool

    for name in ("workspace", "configured"):
        project = tmp_path / name
        project.mkdir()
        (project / "AGENTS.md").write_text(f"Project identity: {name}\n")
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(
        f"terminal:\n  backend: local\n  cwd: {tmp_path / 'configured'}\n"
    )
    monkeypatch.setenv("HERMES_HOME", str(home))
    for key in ("TERMINAL_CWD", "_HERMES_GATEWAY", "HERMES_CRON_SESSION", "_HERMES_LOCAL_CLI_PID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path / launch_name)
    expected = tmp_path / (in_name or launch_name)
    with pytest.raises(SystemExit) as exc:
        main_mod.cmd_chat(_args(in_dir=str(expected) if in_name else None))
    assert exc.value.code == 0

    from cli import load_cli_config
    load_cli_config()
    monkeypatch.setattr(terminal_tool, "_terminal_config_bridge_attempted", False)
    assert terminal_tool._get_env_config()["cwd"] == str(expected)
    load_hermes_dotenv(hermes_home=home, load_external_secrets=False)
    assert os.environ["TERMINAL_CWD"] == str(expected)
    assert resolve_context_cwd() == expected
    prompt = build_context_files_prompt(cwd=str(resolve_context_cwd()), skip_soul=True)
    assert f"Project identity: {expected.name}" in prompt
    other = "configured" if expected.name == "workspace" else "workspace"
    assert f"Project identity: {other}" not in prompt


@pytest.mark.parametrize("surface", [
    "gateway", "cron", "ssh", "docker", "child", "non_cli", "env_target", "explicit_config",
])
def test_cli_origin_does_not_override_other_terminal_surfaces(tmp_path, monkeypatch, surface):
    import os
    from gateway.session_context import _VAR_MAP
    from hermes_cli.config import apply_terminal_config_to_env

    launch, configured = tmp_path / "launch", tmp_path / "configured"
    launch.mkdir()
    configured.mkdir()
    monkeypatch.chdir(launch)
    backend = surface if surface in ("ssh", "docker") else "local"
    home = tmp_path / "profile"
    home.mkdir()
    (home / "config.yaml").write_text(f"terminal:\n  backend: {backend}\n  cwd: {configured}\n")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("TERMINAL_CWD", str(launch))
    monkeypatch.setenv("_HERMES_LOCAL_CLI_PID", str(os.getpid()))
    monkeypatch.delenv("_HERMES_GATEWAY", raising=False)
    if surface == "gateway":
        monkeypatch.setenv("_HERMES_GATEWAY", "1")
    elif surface == "child":
        monkeypatch.setenv("_HERMES_LOCAL_CLI_PID", str(os.getpid() + 1))
    elif surface == "non_cli":
        monkeypatch.delenv("_HERMES_LOCAL_CLI_PID")
    env = dict(os.environ) if surface == "env_target" else None
    config = {"terminal": {"backend": backend, "cwd": str(configured)}} if surface == "explicit_config" else None
    token = _VAR_MAP["HERMES_CRON_SESSION"].set("1" if surface == "cron" else "")
    try:
        result = apply_terminal_config_to_env(env=env, config=config, override=True)
        assert result["TERMINAL_CWD"] == str(configured)
    finally:
        _VAR_MAP["HERMES_CRON_SESSION"].reset(token)


def test_worktree_selection_survives_config_and_dotenv_reload(tmp_path, monkeypatch, main_mod, launched):
    import atexit
    import os
    import subprocess
    from pathlib import Path
    import cli
    import model_tools
    from hermes_cli.env_loader import load_hermes_dotenv
    from agent.runtime_cwd import resolve_agent_cwd
    from tools import terminal_tool

    repo, configured, home = tmp_path / "repo", tmp_path / "configured", tmp_path / "profile"
    for directory in (repo, configured, home):
        directory.mkdir()
    (repo / "AGENTS.md").write_text("Isolated workspace instructions\n")
    for command in (
        ["git", "init"], ["git", "add", "AGENTS.md"],
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"],
    ):
        subprocess.run(command, cwd=repo, check=True, capture_output=True, timeout=10)
    (home / "config.yaml").write_text(
        f"terminal:\n  backend: local\n  cwd: {configured}\nworktree_sync: false\n"
    )
    (home / ".env").write_text("WORKSPACE_RELOAD_PROBE=loaded\n")
    monkeypatch.setenv("WORKSPACE_RELOAD_PROBE", "before")
    monkeypatch.setenv("HERMES_HOME", str(home))
    for key in ("TERMINAL_CWD", "_HERMES_GATEWAY", "HERMES_CRON_SESSION", "_HERMES_LOCAL_CLI_PID"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(cli, "_active_worktree", None)
    monkeypatch.setattr(model_tools, "get_tool_definitions", lambda **kwargs: [])
    monkeypatch.setattr(cli, "_prune_stale_worktrees", lambda *args: None)
    monkeypatch.setattr(cli, "_maintain_pack_health", lambda *args: None)
    with pytest.raises(SystemExit):
        main_mod.cmd_chat(_args(worktree=True))
    monkeypatch.setattr(cli, "CLI_CONFIG", cli.load_cli_config())
    join = cli._start_worktree_setup(False, False, True, False)
    assert join is not None
    info = join()
    assert info is not None
    try:
        expected = Path(info["path"])
        assert expected != repo and expected.is_dir()
        assert Path.cwd() == repo
        assert os.environ["TERMINAL_CWD"] == str(expected)
        load_hermes_dotenv(hermes_home=home, load_external_secrets=False)
        assert os.environ["WORKSPACE_RELOAD_PROBE"] == "loaded"
        cli.load_cli_config()
        monkeypatch.setattr(terminal_tool, "_terminal_config_bridge_attempted", False)
        assert terminal_tool._get_env_config()["cwd"] == str(expected)
        assert resolve_agent_cwd() == expected
    finally:
        atexit.unregister(cli._cleanup_worktree)
        cli._cleanup_worktree(info)
