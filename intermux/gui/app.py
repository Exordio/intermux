from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from intermux.apps import launcher
from intermux import binding
from intermux.binding import BindError, bind
from intermux.gui import theme
from intermux.gui.dialogs import ask_on_running
from intermux.log import setup as setup_logging
from intermux.net import dns, interfaces, namespace
from intermux.net.namespace import Namespace, State
from intermux.system import deps
from intermux.system.privileges import is_root, reexec_as_root
from intermux.system.session import allow_root_on_display, session_env
from intermux.system.shell import CommandError
from intermux.system.users import User, invoking_user

log = logging.getLogger(__name__)

NO_INTERFACES = "No active interfaces"
AUTO_DNS = "Auto"
DNS_CHOICES = [AUTO_DNS] + [f"{name}: {', '.join(servers)}" for name, servers in dns.PRESETS.items()]
ACTIVE_REFRESH_MS = 5000


class App:
    def __init__(self, root: tk.Tk, user: User, session_type: str):
        self.root = root
        self.user = user
        self.pending: list[tuple[str, str, list[str] | None]] = []
        self.states: list[State] = []
        # Held by background actions so that auto-reconnect does not rewire a namespace being removed.
        self.busy = threading.Lock()

        root.title("InterMux")
        root.geometry("1020x790")
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
        self.app_entry = ttk.Entry(self._row(main, "App / Path"))
        self.app_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.app_entry.bind("<Return>", lambda _: self.add())
        self.dns_box = ttk.Combobox(self._row(main, "DNS"), values=DNS_CHOICES)
        self.dns_box.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.dns_box.set(AUTO_DNS)
        ttk.Label(main, foreground=theme.FG, font=("monospace", 9),
                  text="DNS: Auto, a preset or your own servers separated by commas").pack(anchor=tk.W, pady=(0, 8))
        ttk.Button(main, text="Add", width=14, command=self.add).pack(pady=(0, 12))

        self.pending_table = self._section(
            main, "Pending: will be started on Assign",
            {"App": 220, "Interface": 90, "Namespace": 195, "Subnet": 120, "DNS": 275}, height=4,
            buttons=[[("Assign", self.assign), ("Clear", self.clear)]],
        )
        self.active_table = self._section(
            main, "Active: select a namespace or an app in it",
            {"Status": 190, "Interface": 90, "Subnet": 115, "Route": 200, "DNS": 210}, height=8,
            tree_column=("Namespace / App", 150),
            buttons=[
                [("Stop", lambda: self.stop(force=False)), ("Kill", lambda: self.stop(force=True)),
                 ("Restart", self.restart), ("Remove namespace", self.remove)],
                [("Set DNS", self.set_dns), ("Reset Everything", self.reset)],
            ],
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
                 buttons, tree_column: tuple[str, int] | None = None) -> ttk.Treeview:
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
        table = theme.table(frame, columns, height, tree_column)
        table.pack(fill=tk.BOTH, expand=True)
        for button_row in buttons:
            row = ttk.Frame(frame)
            row.pack(pady=(8, 0))
            for text, command in button_row:
                ttk.Button(row, text=text, width=20, command=command).pack(side=tk.LEFT, padx=6)
        return table

    def refresh(self) -> None:
        names = [iface.name for iface in interfaces.selectable()]
        current = self.iface_box.get()
        self.iface_box["values"] = names
        self.iface_box.set(current if current in names else names[0] if names else NO_INTERFACES)
        self.refresh_active()

    def refresh_active(self) -> None:
        selected = self.active_table.selection()
        self.active_table.delete(*self.active_table.get_children())
        self.states = namespace.active()
        for state in self.states:
            entry = state.entry
            dns_text = ", ".join(entry.dns) + (" (auto)" if entry.dns_auto else "")
            self.active_table.insert("", tk.END, iid=entry.namespace, text=entry.namespace, open=True, values=(
                state.connection, entry.interface, entry.subnet, entry.route, dns_text))
            for path, pids in state.running.items():
                self.active_table.insert(entry.namespace, tk.END, iid=f"{entry.namespace}|{path}",
                                         text=os.path.basename(path),
                                         values=(f"PID {', '.join(map(str, pids))}", "", "", "", ""))
        self.active_table.selection_set([iid for iid in selected if self.active_table.exists(iid)])

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
        if self.busy.acquire(blocking=False):
            try:
                for name in namespace.reconnect_lost():
                    log.info("%s reconnected: its interface is back", name)
            finally:
                self.busy.release()
        self.refresh_active()
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

        ns = Namespace.for_interface(iface)
        exists = ns in namespace.existing()
        dns_text = ", ".join(servers) if servers else "unchanged" if exists else "auto"
        self.pending.append((path, iface, servers))
        self.pending_table.insert("", tk.END, values=(
            path, iface, f"{ns.name} ({'existing' if exists else 'new'})", ns.subnet, dns_text))
        self.app_entry.delete(0, tk.END)

    def assign(self) -> None:
        if not self.pending:
            messagebox.showinfo("Info", "No applications to assign.")
            return
        for app, iface, servers in self.pending:
            try:
                bind(app, iface, self.user, lambda path, pids: ask_on_running(self.root, path, pids), servers)
            except (BindError, CommandError) as exc:
                log.exception("Cannot start %s via %s", app, iface)
                messagebox.showerror(f"Cannot start {os.path.basename(app)}", str(exc))
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
