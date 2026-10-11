from __future__ import annotations

import os
import pwd
from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    name: str
    uid: int
    gid: int
    home: str

    @property
    def runtime_dir(self) -> str:
        return f"/run/user/{self.uid}"


def invoking_user() -> User:
    """The real user behind pkexec or sudo. Apps are launched as this user, never as root."""
    entry = None
    pkexec_uid = os.environ.get("PKEXEC_UID", "")
    if pkexec_uid.isdigit():
        entry = _lookup(pwd.getpwuid, int(pkexec_uid))
    if entry is None and os.environ.get("SUDO_USER"):
        entry = _lookup(pwd.getpwnam, os.environ["SUDO_USER"])
    if entry is None:
        entry = pwd.getpwuid(os.getuid())
    return User(entry.pw_name, entry.pw_uid, entry.pw_gid, entry.pw_dir)


def _lookup(func, key):
    try:
        return func(key)
    except KeyError:
        return None
