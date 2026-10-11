"""Environment an app needs to reach the user's display, audio and D-Bus session."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from intermux.system.users import User

SESSION_VARS = (
    "DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "XDG_RUNTIME_DIR", "XAUTHORITY",
    "DBUS_SESSION_BUS_ADDRESS", "PULSE_SERVER", "PIPEWIRE_REMOTE",
)


def session_env(user: User) -> dict[str, str]:
    env = {name: os.environ[name] for name in SESSION_VARS if os.environ.get(name)}

    # sudo and pkexec may strip these, so borrow them from the user's own processes.
    if "DISPLAY" not in env and "WAYLAND_DISPLAY" not in env:
        env.update(_from_user_processes(user.uid, ("DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE")))
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        env.update(_from_user_processes(user.uid, ("DBUS_SESSION_BUS_ADDRESS",)))

    runtime = user.runtime_dir
    env["XDG_RUNTIME_DIR"] = runtime
    if "XDG_SESSION_TYPE" not in env:
        if "DISPLAY" in env:
            env["XDG_SESSION_TYPE"] = "x11"
        elif "WAYLAND_DISPLAY" in env:
            env["XDG_SESSION_TYPE"] = "wayland"
    if "WAYLAND_DISPLAY" in env and not env["WAYLAND_DISPLAY"].startswith("/"):
        env["WAYLAND_DISPLAY"] = f"{runtime}/{env['WAYLAND_DISPLAY']}"

    _set_first_existing(env, "XAUTHORITY", os.path.join(user.home, ".Xauthority"), f"{runtime}/Xauthority")
    _set_first_existing(env, "PULSE_SERVER", f"{runtime}/pulse/native", prefix="unix:")
    _set_first_existing(env, "PIPEWIRE_REMOTE", f"{runtime}/pipewire-0")
    env["HOME"] = user.home
    env["USER"] = user.name
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


def _set_first_existing(env: dict[str, str], name: str, *paths: str, prefix: str = "") -> None:
    if name in env:
        return
    for path in paths:
        if os.path.exists(path):
            env[name] = prefix + path
            return


def _from_user_processes(uid: int, names: tuple[str, ...]) -> dict[str, str]:
    found: dict[str, str] = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid != uid:
                continue
            data = (proc / "environ").read_bytes()
        except OSError:
            continue
        for item in data.split(b"\0"):
            key, sep, value = item.decode(errors="replace").partition("=")
            if sep and key in names and key not in found:
                found[key] = value
        if len(found) == len(names):
            break
    return found
