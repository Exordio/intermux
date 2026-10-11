import os
import sys
from pathlib import Path

from intermux.system.session import SESSION_VARS
from intermux.system.shell import which

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


def is_root() -> bool:
    return os.geteuid() == 0


def reexec_as_root(module: str) -> None:
    """Replace the current process with `python -m module` running as root.

    pkexec and sudo both clear the environment, so the session variables are
    passed explicitly through env(1).
    """
    env = [f"{name}={os.environ[name]}" for name in SESSION_VARS if os.environ.get(name)]
    env.append(f"PYTHONPATH={PROJECT_ROOT}")
    launcher = "pkexec" if which("pkexec") else "sudo"
    os.execvp(launcher, [launcher, "env", *env, sys.executable, "-m", module])
