"""CLI launch workspace resolution, before agent initialization."""

import os
import sys
from typing import Any, cast


def _resolve_chat_session_args(args, use_tui: bool) -> None:
    """Resolve --in, resume and workspace cwd before marking the owning CLI process."""
    from hermes_cli import main

    main._apply_in_dir(args)

    # --in runs first so workspace-scoped latest/continue lookups use the selected directory.
    resume_raw = getattr(args, "resume", None)
    if isinstance(resume_raw, str) and resume_raw.strip().lower() == "latest":
        last_id = main._latest_session_id(use_tui)
        if last_id:
            args.resume = last_id
        else:
            kind = "TUI" if use_tui else "CLI"
            print(f"No previous {kind} session found to resume.")
            print("Use 'hermes sessions list' to see available sessions.")
            sys.exit(1)

    main._resolve_continue_arg(args, use_tui=use_tui)
    main._import_foreign_resume(args)

    resume_val = getattr(args, "resume", None)
    if resume_val:
        args.resume = main._resolve_session_by_name_or_id(resume_val) or resume_val

    # A worktree owns its own directory; explicit --in also opts out of resume cwd restore.
    if (
        getattr(args, "resume", None)
        and not getattr(args, "no_restore_cwd", False)
        and not getattr(args, "worktree", False)
    ):
        with main._session_db() as db:
            saved_cwd = ((cast(Any, db).get_session(args.resume) or {}).get("cwd") or "").strip()
            if saved_cwd and not os.path.isdir(saved_cwd):
                print(f"⚠ session's recorded dir is gone ({saved_cwd}); staying in {os.getcwd()}")
            elif saved_cwd and os.path.realpath(saved_cwd) != os.path.realpath(os.getcwd()):
                os.chdir(saved_cwd)
                print(f"↪ restored workspace dir: {saved_cwd}")

    # Child launchers must not inherit ownership of the parent's local CLI workspace.
    os.environ["_HERMES_LOCAL_CLI_PID"] = str(os.getpid())
