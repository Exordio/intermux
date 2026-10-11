from __future__ import annotations

import logging
import os
import tkinter as tk
from tkinter import messagebox, ttk

from intermux.apps import launcher
from intermux.binding import BindError, bind
from intermux.gui import theme
from intermux.gui.dialogs import ask_on_running
from intermux.log import setup as setup_logging
from intermux.net import interfaces, namespace
from intermux.system import deps
from intermux.system.privileges import is_root, reexec_as_root
from intermux.system.session import allow_root_on_display, session_env
from intermux.system.shell import CommandError
from intermux.system.users import User, invoking_user

log = logging.getLogger(__name__)

NO_INTERFACES = "No active interfaces"


class App:
    def __init__(self, root: tk.Tk, user: User, session_type: str):
        self.root = root
        self.user = user
        self.pending: list[tuple[str, str]] = []

        root.title("InterMux")
        root.geometry("820x620")
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
        ttk.Button(main, text="Add", width=14, command=self.add).pack(pady=(0, 16))

        lists = ttk.Frame(main)
        lists.pack(fill=tk.BOTH, expand=True, pady=(0, 16))
        self.pending_list = self._list(lists, "Pending", padx=(0, 8))
        self.active_list = self._list(lists, "Active", padx=0)

        buttons = ttk.Frame(main)
        buttons.pack()
        for text, command in (("Assign", self.assign), ("Clear", self.clear), ("Reset Everything", self.reset)):
            ttk.Button(buttons, text=text, width=20, command=command).pack(side=tk.LEFT, padx=6)

        self.refresh()

    @staticmethod
    def _row(parent: tk.Widget, label: str) -> ttk.Frame:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(row, text=label, width=18, font=theme.FONT).pack(side=tk.LEFT)
        return row

    @staticmethod
    def _list(parent: tk.Widget, title: str, padx) -> tk.Listbox:
        frame = ttk.LabelFrame(parent, text=title, padding=8)
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=padx)
        listbox = theme.listbox(frame)
        listbox.pack(fill=tk.BOTH, expand=True)
        return listbox

    def refresh(self) -> None:
        names = [iface.name for iface in interfaces.selectable()]
        current = self.iface_box.get()
        self.iface_box["values"] = names
        self.iface_box.set(current if current in names else names[0] if names else NO_INTERFACES)

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
        self.pending.append((path, iface))
        self.pending_list.insert(tk.END, f"{path} -> {iface}")
        self.app_entry.delete(0, tk.END)

    def assign(self) -> None:
        if not self.pending:
            messagebox.showinfo("Info", "No applications to assign.")
            return
        for app, iface in self.pending:
            try:
                ns = bind(app, iface, self.user, lambda path, pids: ask_on_running(self.root, path, pids))
            except (BindError, CommandError) as exc:
                log.exception("Cannot start %s via %s", app, iface)
                messagebox.showerror(f"Cannot start {os.path.basename(app)}", str(exc))
                continue
            if ns:
                self.active_list.insert(tk.END, f"{app} -> {iface} ({ns.name})")
        self.clear()

    def clear(self) -> None:
        self.pending.clear()
        self.pending_list.delete(0, tk.END)

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
        self.active_list.delete(0, tk.END)
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
