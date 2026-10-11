from __future__ import annotations

import logging
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from intermux.apps import launcher
from intermux import binding
from intermux.binding import BindError, bind
from intermux.gui import theme
from intermux.gui.dialogs import ask_on_running
from intermux.gui.history import History
from intermux.log import setup as setup_logging
from intermux.net import dns, interfaces, namespace, shaping, traffic
from intermux.net.namespace import State
from intermux.system import deps
from intermux.system.privileges import is_root, reexec_as_root
from intermux.system.session import allow_root_on_display, session_env
from intermux.system.shell import CommandError
from intermux.system.users import User, invoking_user

log = logging.getLogger(__name__)

NO_INTERFACES = "No active interfaces"
AUTO_DNS = "Auto"
DNS_CHOICES = [AUTO_DNS] + [f"{name}: {', '.join(servers)}" for name, servers in dns.PRESETS.items()]
ACTIVE_REFRESH_MS = 2000


class App:
    def __init__(self, root: tk.Tk, user: User, session_type: str):
        self.root = root
        self.user = user
        self.pending: list[tuple[str, str, list[str] | None]] = []
        self.states: list[State] = []
        self.history = History(user)
        self.last_traffic: dict[str, tuple[float, traffic.Counters]] = {}
        # Held by background actions so that auto-reconnect does not rewire a namespace being removed.
        self.busy = threading.Lock()

        root.title("InterMux")
        root.geometry("1200x830")
        theme.apply(root)

        main = ttk.Frame(root, padding=20)
        main.pack(fill=tk.BOTH, expand=True)

        missing = deps.missing()
        if missing:
            hints = "\n".join(f"  {tool}: {hint}" for tool, hint in missing)
            tk.Label(
                main, text=f"Missing dependencies, some features may not work:\n{hints}",
                bg=theme.WARN_BG, fg=theme.WARN, font=("monospace", 9),
                justify=tk.LEFT, anchor="w", padx=10, pady=6,
            ).pack(fill=tk.X, pady=(0, 12))

        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 16))
        ttk.Label(header, text=f"InterMux [{session_type.upper()}]",
                  font=("monospace", 15, "bold"), foreground=theme.ACCENT).pack(side=tk.LEFT)
        tk.Label(header, text=f"Apps run as: {user.name}",
                 bg=theme.BG, fg=theme.OK, font=("monospace", 9)).pack(side=tk.LEFT, padx=12)
        ttk.Button(header, text="Refresh", width=12, command=self.refresh).pack(side=tk.RIGHT)

        self.iface_box = ttk.Combobox(self._row(main, "Interface"), state="readonly")
        self.iface_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app_entry = ttk.Combobox(self._row(main, "App / Path"), values=self.history.apps)
        self.app_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app_entry.bind("<Return>", lambda _: self.add())
        self.app_entry.bind("<<ComboboxSelected>>", lambda _: self._restore_from_history())
        self.dns_box = ttk.Combobox(self._row(main, "DNS"), values=DNS_CHOICES)
        self.dns_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.dns_box.set(AUTO_DNS)
        ttk.Label(main, foreground=theme.FG, font=("monospace", 9),
                  text="DNS: Auto, a preset or your own servers separated by commas").pack(anchor=tk.W, pady=(0, 8))
        ttk.Button(main, text="Add", width=14, command=self.add).pack(pady=(0, 12))

        self.pending_table = self._section(
            main, "Pending: will be started on Assign",
            {"App": 260, "Interface": 100, "Namespace": 220, "Subnet": 130, "DNS": 330}, height=4,
            buttons=[[("Assign", self.assign), ("Clear", self.clear)]],
        )
        self.active_table = self._section(
            main, "Active: select a namespace or an app in it",
            {"Status": 150, "Interface": 90, "Route": 120, "DNS": 205, "Download": 145, "Upload": 145,
             "Limit, Mbit/s": 115}, height=8,
            tree_column=("Namespace / App", 135),
            buttons=[
                [("Stop", lambda: self.stop(force=False)), ("Kill", lambda: self.stop(force=True)),
                 ("Restart", self.restart), ("Remove namespace", self.remove)],
                [("Move to interface", self.move), ("Set DNS", self.set_dns), ("Set limit", self.set_limits),
                 ("Reset Everything", self.reset)],
            ],
            controls=self._limit_controls,
        )

        self.refresh()
        self._schedule_active_refresh()

    @staticmethod
    def _row(parent: tk.Widget, label: str) -> ttk.Frame:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text=label, width=18, font=theme.FONT).pack(side=tk.LEFT)
        return row

    @staticmethod
    def _section(parent: tk.Widget, title: str, columns: dict[str, int], height: int,
                 buttons, tree_column: tuple[str, int] | None = None, controls=None) -> ttk.Treeview:
        """Labelled table with rows of buttons under it; controls(row) may fill a row before the buttons."""
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        table = theme.table(frame, columns, height, tree_column)
        table.pack(fill=tk.BOTH, expand=True)
        if controls:
            row = ttk.Frame(frame)
            row.pack(pady=(8, 0))
            controls(row)
        for button_row in buttons:
            row = ttk.Frame(frame)
            row.pack(pady=(8, 0))
            for text, command in button_row:
                ttk.Button(row, text=text, width=20, command=command).pack(side=tk.LEFT, padx=6)
        return table

    def _limit_controls(self, row: ttk.Frame) -> None:
        ttk.Label(row, text="Limit, Mbit/s (empty: none)   down", font=theme.FONT).pack(side=tk.LEFT)
        self.limit_down = ttk.Entry(row, width=8)
        self.limit_down.pack(side=tk.LEFT, padx=(6, 12))
        ttk.Label(row, text="up", font=theme.FONT).pack(side=tk.LEFT)
        self.limit_up = ttk.Entry(row, width=8)
        self.limit_up.pack(side=tk.LEFT, padx=6)

    def refresh(self) -> None:
        names = [iface.name for iface in interfaces.selectable()]
        current = self.iface_box.get()
        self.iface_box["values"] = names
        self.iface_box.set(current if current in names else names[0] if names else NO_INTERFACES)
        self.refresh_active()

    def refresh_active(self, states: list[State] | None = None) -> None:
        selected = self.active_table.selection()
        self.active_table.delete(*self.active_table.get_children())
        self.states = namespace.active() if states is None else states
        for state in self.states:
            entry = state.entry
            dns_text = ", ".join(entry.dns) + (" (auto)" if entry.dns_auto else "")
            down, up = self._traffic_text(entry.namespace, state.traffic)
            route = entry.route.replace(f" dev {entry.interface}", "") or entry.route
            limit = f"{shaping.format_mbit(entry.limit_down)} / {shaping.format_mbit(entry.limit_up)}"
            self.active_table.insert("", tk.END, iid=entry.namespace, text=entry.namespace, open=True, values=(
                state.connection, entry.interface, route, dns_text, down, up, limit))
            for path, pids in state.running.items():
                self.active_table.insert(entry.namespace, tk.END, iid=f"{entry.namespace}|{path}",
                                         text=os.path.basename(path),
                                         values=(f"PID {', '.join(map(str, pids))}",))
        self.active_table.selection_set([iid for iid in selected if self.active_table.exists(iid)])

    def _traffic_text(self, name: str, counters: traffic.Counters | None) -> tuple[str, str]:
        """Totals with the rate since the previous refresh."""
        if counters is None:
            return "-", "-"
        now = time.monotonic()
        previous_time, previous = self.last_traffic.get(name, (now, counters))
        self.last_traffic[name] = (now, counters)
        elapsed = now - previous_time
        result = []
        for total, before in ((counters.down, previous.down), (counters.up, previous.up)):
            rate = (total - before) / elapsed if elapsed > 0 and total >= before else 0
            result.append(f"{traffic.format_bytes(total)}, {traffic.format_bytes(rate)}/s")
        return result[0], result[1]

    def _selection(self) -> tuple[State, str | None] | None:
        """Selected namespace state and app path (None when the namespace row itself is selected)."""
        selected = self.active_table.selection()
        name, _, path = selected[0].partition("|") if selected else ("", "", "")
        state = next((state for state in self.states if state.entry.namespace == name), None)
        if state is None:
            messagebox.showinfo("Info", "Select a namespace or an app in the Active list.")
            return None
        return state, path or None

    def _in_background(self, action: str, func) -> None:
        """Stopping apps may wait for them for seconds, so it runs off the Tk thread."""
        def work() -> None:
            with self.busy:
                try:
                    func()
                except (CommandError, OSError) as exc:
                    log.exception("%s failed", action)
                    self.root.after(0, lambda: messagebox.showerror(f"{action} failed", str(exc)))
            self.root.after(0, self.refresh_active)

        threading.Thread(target=work, daemon=True).start()

    def stop(self, force: bool) -> None:
        selection = self._selection()
        if not selection:
            return
        state, path = selection
        if path:
            self._in_background("Stop", lambda: binding.stop_app(state, path, force))
        elif messagebox.askyesno("Stop", f"Stop everything running in {state.entry.namespace}?"):
            self._in_background("Stop", lambda: binding.stop_all(state, force))

    def restart(self) -> None:
        selection = self._selection()
        if not selection:
            return
        state, path = selection
        paths = [path] if path else list(state.running)
        self._in_background("Restart", lambda: [binding.restart_app(state, p, self.user) for p in paths])

    def remove(self) -> None:
        selection = self._selection()
        if selection and messagebox.askyesno(
            "Remove namespace",
            f"Stop everything running in {selection[0].entry.namespace} and remove the namespace?",
        ):
            self._in_background("Remove", lambda: binding.remove_namespace(selection[0]))

    def _schedule_active_refresh(self) -> None:
        states = namespace.active()
        if self.busy.acquire(blocking=False):
            try:
                reconnected = namespace.reconnect_lost(states)
            finally:
                self.busy.release()
            for name in reconnected:
                log.info("%s reconnected: its interface is back", name)
            if reconnected:
                states = namespace.active()
        self.refresh_active(states)
        self.root.after(ACTIVE_REFRESH_MS, self._schedule_active_refresh)

    def _dns_choice(self) -> list[str] | None:
        text = self.dns_box.get().strip()
        return None if not text or text == AUTO_DNS else dns.parse(text)

    def add(self) -> None:
        app, iface = self.app_entry.get().strip(), self.iface_box.get()
        if not app or iface == NO_INTERFACES:
            messagebox.showerror("Error", "Enter an application and select an interface.")
            return
        path = launcher.resolve(app)
        if path is None:
            messagebox.showerror(
                "Application not found",
                f"Could not find '{app}'.\n\nEnter a command name from PATH (firefox) "
                "or a full path (/usr/lib/firefox/firefox).",
            )
            return
        try:
            servers = self._dns_choice()
        except ValueError as exc:
            messagebox.showerror("Invalid DNS", str(exc))
            return

        ns = namespace.for_interface(iface)
        exists = ns in namespace.existing()
        dns_text = ", ".join(servers) if servers else "unchanged" if exists else "auto"
        self.pending.append((path, iface, servers))
        self.pending_table.insert("", tk.END, values=(
            path, iface, f"{ns.name} ({'existing' if exists else 'new'})", ns.subnet, dns_text))
        self.app_entry.delete(0, tk.END)

    def _restore_from_history(self) -> None:
        """Picking an app from the history brings back the interface and DNS it was started with."""
        item = self.history.find(self.app_entry.get())
        if item is None:
            return
        if item.interface in self.iface_box["values"]:
            self.iface_box.set(item.interface)
        self.dns_box.set(item.dns)

    def assign(self) -> None:
        if not self.pending:
            messagebox.showinfo("Info", "No applications to assign.")
            return
        for app, iface, servers in self.pending:
            try:
                ns = bind(app, iface, self.user, lambda path, pids: ask_on_running(self.root, path, pids), servers)
            except (BindError, CommandError) as exc:
                log.exception("Cannot start %s via %s", app, iface)
                messagebox.showerror(f"Cannot start {os.path.basename(app)}", str(exc))
                continue
            if ns:
                self.history.add(app, iface, ", ".join(servers) if servers else AUTO_DNS)
        self.app_entry["values"] = self.history.apps
        self.clear()
        self.refresh_active()

    def clear(self) -> None:
        self.pending.clear()
        self.pending_table.delete(*self.pending_table.get_children())

    def set_dns(self) -> None:
        selection = self._selection()
        if not selection:
            return
        try:
            servers = self._dns_choice()
        except ValueError as exc:
            messagebox.showerror("Invalid DNS", str(exc))
            return
        namespace.set_dns(selection[0].ns, servers)
        self.refresh_active()

    def move(self) -> None:
        """Route the selected namespace through the interface chosen at the top of the window."""
        selection = self._selection()
        if not selection:
            return
        state = selection[0]
        target = interfaces.find(self.iface_box.get())
        if target is None or not target.up:
            messagebox.showerror("Move", "Select an active interface at the top of the window.")
            return
        if target.name == state.entry.interface:
            return
        if messagebox.askyesno(
            "Move to interface",
            f"Route {state.entry.namespace} through {target.name} instead of {state.entry.interface}?\n\n"
            "Apps keep running, their open connections will break.",
        ):
            namespace.move(state.ns, target)
            self.refresh_active()

    def set_limits(self) -> None:
        selection = self._selection()
        if not selection:
            return
        try:
            down = shaping.parse_mbit(self.limit_down.get())
            up = shaping.parse_mbit(self.limit_up.get())
        except ValueError as exc:
            messagebox.showerror("Invalid limit", f"Enter a number of Mbit/s or leave the field empty.\n\n{exc}")
            return
        namespace.set_limits(selection[0].ns, down, up)
        self.refresh_active()

    def reset(self) -> None:
        if not messagebox.askyesno(
            "Reset", "Remove all namespaces, routes and firewall rules created by InterMux?"
        ):
            return
        try:
            namespace.reset()
        except OSError as exc:
            log.exception("Reset failed")
            messagebox.showerror("Reset failed", str(exc))
        self.refresh()


def main() -> None:
    if not is_root():
        reexec_as_root("intermux.gui")
    setup_logging()
    user = invoking_user()
    env = session_env(user)
    allow_root_on_display(user, env)

    root = tk.Tk()
    App(root, user, env.get("XDG_SESSION_TYPE", "x11"))
    root.mainloop()
