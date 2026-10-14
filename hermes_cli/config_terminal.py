"""Terminal config bridging, including local CLI workspace precedence."""

import os
import sys
from typing import Any, Optional, MutableMapping


def apply_terminal_config_to_env(
    *, env: Optional[dict[str, str]] = None, config: Optional[dict[str, Any]] = None,
    override: Optional[bool] = None,
) -> MutableMapping[str, str]:
    """Apply explicit terminal keys; an owning local CLI keeps its selected workspace."""
    from hermes_cli.config import (
        TERMINAL_CONFIG_ENV_MAP, read_raw_config, load_config_readonly,
        _terminal_config_value_is_bridgeable, _is_ssh_remote_tilde_cwd, _terminal_env_value,
    )

    target = os.environ if env is None else env
    raw_terminal_cfg = read_raw_config().get("terminal")
    file_has_terminal_config = isinstance(raw_terminal_cfg, dict)
    raw_terminal_cfg = raw_terminal_cfg if file_has_terminal_config else {}
    should_override = file_has_terminal_config if override is None else override

    cfg = config if config is not None else load_config_readonly()
    terminal_cfg = cfg.get("terminal", {}) if isinstance(cfg, dict) else {}
    if not isinstance(terminal_cfg, dict):
        return target

    # Defaults backfill; only caller-supplied config or raw file keys override existing values.
    explicit_keys = terminal_cfg.keys() if config is not None else raw_terminal_cfg.keys()
    backend_sources = (terminal_cfg.get("backend"), target.get("TERMINAL_ENV"))
    if not (config is not None or "backend" in raw_terminal_cfg):
        backend_sources = backend_sources[::-1]
    terminal_backend = str(backend_sources[0] or backend_sources[1] or "")

    # Preserve whether a launcher pinned the image; children inherit both slots.
    if should_override and "docker_image" in explicit_keys:
        target["TERMINAL_DOCKER_IMAGE_PINNED"] = "1"
    elif "TERMINAL_DOCKER_IMAGE_PINNED" not in target:
        target["TERMINAL_DOCKER_IMAGE_PINNED"] = "1" if "TERMINAL_DOCKER_IMAGE" in target else "0"

    for cfg_key, env_var in TERMINAL_CONFIG_ENV_MAP.items():
        if cfg_key not in terminal_cfg:
            continue
        if (
            cfg_key == "cwd" and terminal_backend == "local"
            and env is None and config is None
            and target.get("_HERMES_LOCAL_CLI_PID") == str(os.getpid())
            and target.get("_HERMES_GATEWAY") != "1"
        ):
            from gateway.session_context import get_session_env

            if get_session_env("HERMES_CRON_SESSION") != "1":
                # Worktree selection changes TERMINAL_CWD, not the process cwd. Its metadata
                # remains authoritative even if a dotenv reload overwrote the environment slot.
                worktree = getattr(sys.modules.get("cli"), "_active_worktree", None)
                target[env_var] = worktree["path"] if worktree else os.getcwd()
                continue
        value = terminal_cfg[cfg_key]
        if not _terminal_config_value_is_bridgeable(cfg_key, value):
            continue
        if cfg_key == "cwd":
            raw_cwd = str(value or "").strip()
            if isinstance(value, str) and not _is_ssh_remote_tilde_cwd(terminal_backend, raw_cwd):
                value = os.path.expanduser(value)
        if (should_override and cfg_key in explicit_keys) or env_var not in target:
            target[env_var] = _terminal_env_value(value)
    return target
