"""Finding and running the writer's text editor."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# Tried in order when neither $VISUAL nor $EDITOR is set. Editors people install
# on purpose come before the ones that ship with the system.
FALLBACK_EDITORS = ("hx", "helix", "nvim", "micro", "nano", "vim", "vi")

COMMAND_NOT_FOUND = 127


def editor_command() -> tuple[str, str] | None:
    """The editor command and where it came from, e.g. ``("nvim", "$EDITOR")``."""
    for variable in ("VISUAL", "EDITOR"):
        if command := os.environ.get(variable, "").strip():
            return command, f"${variable}"
    for name in FALLBACK_EDITORS:
        if shutil.which(name):
            return name, "PATH"
    return None


def run_editor(command: str, path: Path) -> int:
    """Open ``path`` in the editor and wait until it closes. Returns the exit status."""
    if os.name == "nt":
        args = [*shlex.split(command, posix=False), str(path)]
    else:
        # Like git, hand the command to the shell so values such as `code --wait`
        # or `emacsclient -t -a ""` work as they do on the command line.
        args = ["/bin/sh", "-c", f'{command} "$@"', command, str(path)]
    terminal = sys.stdout.isatty()
    if terminal:
        # Only seen while a GUI editor is open; tidied away again afterwards.
        print(f"wri is waiting for {command} to finish with {path.name}…", flush=True)
    try:
        return subprocess.run(args, check=False).returncode
    finally:
        if terminal:
            sys.stdout.write("\x1b[1A\x1b[2K")
            sys.stdout.flush()
