import os
import sys
from pathlib import Path

from intermux.system.session import SESSION_VARS
from intermux.system.shell import which

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


def is_root() -> bool:
    return os.geteuid() == 0


def reexec_as_root(module: str) -> None:
    """Replace the current process with the module running as root.

    pkexec and sudo both clear the environment, so the session variables are
    passed explicitly through env(1).
    """
    env = [f"{name}={os.environ[name]}" for name in SESSION_VARS if os.environ.get(name)]
    launcher = "pkexec" if which("pkexec") else "sudo"
    os.execvp(launcher, [launcher, "env", *env, *module_command(module)])


def module_command(module: str) -> list[str]:
    """Like `python -m module`, but InterMux is imported from PROJECT_ROOT even when the current
    directory holds another copy: -m would put the current directory first on sys.path."""
    bootstrap = (f"import runpy, sys; sys.path.insert(0, {PROJECT_ROOT!r}); "
                 f"runpy.run_module({module!r}, run_name='__main__', alter_sys=True)")
    return [sys.executable, "-c", bootstrap]
