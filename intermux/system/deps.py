"""Checks for the system tools InterMux relies on."""

from __future__ import annotations

from intermux.system.shell import which

_INSTALL = {
    "apt": "sudo apt install {}",
    "pacman": "sudo pacman -S {}",
    "dnf": "sudo dnf install {}",
    "zypper": "sudo zypper install {}",
    "apk": "sudo apk add {}",
}

_DISTRO_FAMILIES = {
    "apt": ("debian", "ubuntu"),
    "pacman": ("arch",),
    "dnf": ("fedora", "rhel"),
    "zypper": ("suse", "opensuse"),
    "apk": ("alpine",),
}

# tool -> (package name, overrides per package manager)
_TOOLS = {
    "ip": ("iproute2", {"dnf": "iproute"}),
    "iptables": ("iptables", {}),
    "sysctl": ("procps", {"pacman": "procps-ng", "dnf": "procps-ng"}),
    "sudo": ("sudo", {}),
    "pkexec": ("polkit", {"apt": "pkexec"}),
    "xhost": ("xhost", {"apt": "x11-xserver-utils", "pacman": "xorg-xhost"}),
}


def missing() -> list[tuple[str, str]]:
    """Missing tools as (tool, install hint) pairs."""
    manager = package_manager()
    template = _INSTALL.get(manager, "install package {} with your package manager")
    result = []
    for tool, (package, overrides) in _TOOLS.items():
        if not which(tool):
            result.append((tool, template.format(overrides.get(manager, package))))
    return result


def package_manager() -> str | None:
    ids = _os_release_ids()
    for manager, families in _DISTRO_FAMILIES.items():
        if any(family in ids for family in families):
            return manager
    return next((manager for manager in _INSTALL if which(manager)), None)


def _os_release_ids() -> list[str]:
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            with open(path) as f:
                fields = dict(line.rstrip("\n").split("=", 1) for line in f if "=" in line)
        except OSError:
            continue
        return f"{fields.get('ID', '')} {fields.get('ID_LIKE', '')}".replace('"', "").lower().split()
    return []
