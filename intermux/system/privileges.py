import os
import sys
from pathlib import Path

from intermux.system.session import SESSION_VARS
from intermux.system.shell import which

PROJECT_ROOT = str(Path(__file__).resolve().parents[2])

_ENV_OPTION = "--session-env="


def is_root() -> bool:
    return os.geteuid() == 0


def reexec_as_root(module: str) -> None:
    """Replace the current process with the module running as root.

    pkexec and sudo both clear the environment, so the session variables are passed
    as arguments, which restore_session_env() turns back into variables.
    """
    env = [f"{_ENV_OPTION}{name}={os.environ[name]}" for name in SESSION_VARS if os.environ.get(name)]
    launcher = "pkexec" if which("pkexec") else "sudo"
    os.execvp(launcher, [launcher, *_own_command(module), *env])


def restore_session_env() -> None:
    args = []
    for arg in sys.argv[1:]:
        name, sep, value = arg.removeprefix(_ENV_OPTION).partition("=")
        if arg.startswith(_ENV_OPTION) and sep and name in SESSION_VARS:
            os.environ[name] = value
        else:
            args.append(arg)
    sys.argv[1:] = args


def _own_command(module: str) -> list[str]:
    """The installed launcher this process was started from, when there is one: polkit finds
    the InterMux action, with its message and icon, by the path of the program pkexec runs."""
    launcher = os.path.abspath(sys.argv[0])
    if not launcher.endswith(".py") and os.path.isfile(launcher) and os.access(launcher, os.X_OK):
        return [launcher]
    return module_command(module)


def module_command(module: str) -> list[str]:
    """Like `python -m module`, but InterMux is imported from PROJECT_ROOT even when the current
    directory holds another copy: -m would put the current directory first on sys.path."""
    bootstrap = (f"import runpy, sys; sys.path.insert(0, {PROJECT_ROOT!r}); "
                 f"runpy.run_module({module!r}, run_name='__main__', alter_sys=True)")
    return [sys.executable, "-c", bootstrap]
