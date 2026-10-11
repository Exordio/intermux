"""Firefox refuses to start a second instance on a locked profile and hands URLs to a running one,
so inside a namespace it needs -new-instance --no-remote and a cleared lock."""

from __future__ import annotations

import configparser
import os

from intermux.system.users import User, give_to


def is_firefox(app: str) -> bool:
    return "firefox" in os.path.basename(app).lower()


def launch_flags(user: User, iface: str, separate_profile: bool) -> list[str]:
    flags = ["-new-instance", "--no-remote"]
    if separate_profile:
        profile = _interface_profile(user, iface)
        flags += ["--profile", profile]
    else:
        profile = _default_profile(user.home)
    if profile:
        _remove_locks(profile)
    return flags


def _profiles_dir(home: str) -> str:
    return os.path.join(home, ".mozilla", "firefox")


def _interface_profile(user: User, iface: str) -> str:
    profile = os.path.join(_profiles_dir(user.home), f"intermux-{iface}")
    os.makedirs(profile, exist_ok=True)
    give_to(user, profile)
    return profile


def _default_profile(home: str) -> str | None:
    config = configparser.ConfigParser(interpolation=None)
    if not config.read(os.path.join(_profiles_dir(home), "profiles.ini")):
        return None
    profiles = sorted((s for s in config.values() if s.get("Path")), key=lambda s: s.get("Default") != "1")
    if not profiles:
        return None
    path = profiles[0]["Path"]
    return os.path.join(_profiles_dir(home), path) if profiles[0].get("IsRelative", "1") == "1" else path


def _remove_locks(profile: str) -> None:
    for name in ("lock", ".parentlock"):
        path = os.path.join(profile, name)
        if os.path.lexists(path):
            os.remove(path)
