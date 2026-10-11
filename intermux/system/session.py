"""Environment of the user's desktop session for the apps InterMux starts."""

from __future__ import annotations

import codecs
import os
import subprocess
from pathlib import Path

from intermux.system.shell import run
from intermux.system.users import User

SESSION_VARS = (
    "DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "XDG_RUNTIME_DIR", "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS", "PULSE_SERVER", "PIPEWIRE_REMOTE",
)


# Shell bookkeeping of whatever process the environment was taken from.
_DROPPED = ("PWD", "OLDPWD", "SHLVL", "_")


def session_env(user: User) -> dict[str, str]:
    """The environment the desktop gives to apps it starts itself.

    Apps need more than the display: portals and toolkits look at XDG_CURRENT_DESKTOP,
    XDG_SESSION_TYPE, XDG_DATA_DIRS, LANG and so on. sudo and pkexec strip all of it,
    so it comes from the systemd user manager, which desktops keep up to date, or
    from a graphical process of the user. The variables InterMux was started with win.
    """
    env = _systemd_user_env(user) or _graphical_process_env(user.uid)
    env.update({name: os.environ[name] for name in SESSION_VARS if os.environ.get(name)})
    for name in _DROPPED:
        env.pop(name, None)

    runtime = user.runtime_dir
    env["XDG_RUNTIME_DIR"] = runtime
    # Wayland sessions have DISPLAY too (XWayland), so WAYLAND_DISPLAY decides.
    if "XDG_SESSION_TYPE" not in env:
        if "WAYLAND_DISPLAY" in env:
            env["XDG_SESSION_TYPE"] = "wayland"
        elif "DISPLAY" in env:
            env["XDG_SESSION_TYPE"] = "x11"
    _set_first_existing(env, "XAUTHORITY", os.path.join(user.home, ".Xauthority"), f"{runtime}/Xauthority")
    env["HOME"] = user.home
    env["USER"] = env["LOGNAME"] = user.name
    return env


def is_wayland(env: dict[str, str]) -> bool:
    return env.get("XDG_SESSION_TYPE") == "wayland" or ("WAYLAND_DISPLAY" in env and "DISPLAY" not in env)


def allow_root_on_display(user: User, env: dict[str, str]) -> None:
    """Grant root and the user access to the X display. Wayland sessions are skipped."""
    if is_wayland(env) or "DISPLAY" not in env:
        return
    try:
        subprocess.run(
            ["xhost", f"+SI:localuser:{user.name}", "+SI:localuser:root"],
            env={**os.environ, "DISPLAY": env["DISPLAY"]},
            capture_output=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _set_first_existing(env: dict[str, str], name: str, *paths: str) -> None:
    if name in env:
        return
    for path in paths:
        if os.path.exists(path):
            env[name] = path
            return


def _systemd_user_env(user: User) -> dict[str, str]:
    command = ["systemctl", "--user", "show-environment"]
    if os.getuid() != user.uid:
        command = ["sudo", "-u", user.name, "env", f"XDG_RUNTIME_DIR={user.runtime_dir}", *command]
    env = {}
    for line in run(*command, check=False, timeout=3).splitlines():
        name, sep, value = line.partition("=")
        if sep:
            # Values with special characters are printed as $'...' with C escapes.
            if value.startswith("$'") and value.endswith("'"):
                value = codecs.decode(value[2:-1].encode("latin-1", "backslashreplace"), "unicode_escape")
            env[name] = value
    return env if "DISPLAY" in env or "WAYLAND_DISPLAY" in env else {}


def _graphical_process_env(uid: int) -> dict[str, str]:
    """Whole environment of the first process of the user that has a display."""
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            data = (proc / "environ").read_bytes()
        except OSError:
            continue
        env = dict(item.decode(errors="replace").partition("=")[::2] for item in data.split(b"\0") if b"=" in item)
        if "DISPLAY" in env or "WAYLAND_DISPLAY" in env:
            return env
    return {}
