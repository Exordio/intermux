"""Bandwidth limits with a token bucket filter (tc tbf) on the veth pair of a namespace.

Shaping works on egress only, so the download limit sits on the host end
(it transmits into the namespace) and the upload limit on the namespace end.
"""

from __future__ import annotations

from intermux.system.shell import IP, run, which

TC = which("tc") or "tc"


def set_limit(device: str, mbit: float | None, namespace: str | None = None) -> None:
    """Limit the device to mbit megabits per second; None or 0 removes the limit."""
    prefix = (IP, "netns", "exec", namespace) if namespace else ()
    if not mbit:
        run(*prefix, TC, "qdisc", "del", "dev", device, "root", check=False)
        return
    kbit = int(mbit * 1000)
    # About 10 ms worth of traffic, but never less than a few full-size packets.
    burst = max(kbit * 1000 // 8 // 100, 16 * 1024)
    run(*prefix, TC, "qdisc", "replace", "dev", device, "root",
        "tbf", "rate", f"{kbit}kbit", "burst", str(burst), "latency", "100ms")


def parse_mbit(text: str) -> float | None:
    """Limit from user input: empty, "0" or "none" means no limit."""
    text = text.strip().replace(",", ".")
    if not text or text.lower() == "none":
        return None
    value = float(text)
    if value < 0:
        raise ValueError("A limit cannot be negative")
    return value or None


def format_mbit(mbit: float | None) -> str:
    return f"{mbit:g}" if mbit else "-"
