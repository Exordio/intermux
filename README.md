# InterMux

English | [Русский](README.RU.md)

A Linux tool that runs an application so that all of its network traffic goes through an interface you choose. For example: a browser through Wi-Fi, a torrent client through a USB modem or Ethernet, something else through a VPN.

This is a fork of [Rishi-Bhati/intermux](https://github.com/Rishi-Bhati/intermux). It runs on Linux only; Windows support is not planned in this fork and was removed by reverting the upstream commits that added it.

![InterMux window](https://i.imgur.com/nRBznni.png)

## How it works

For every interface you pick, InterMux creates a separate network namespace and starts the application inside it:

1. A namespace `ns_<hash>` is created, where `<hash>` is the first 8 characters of the MD5 of the interface name. All other names and numbers are derived from the same hash. If the name or the subnet is already taken (for example, a namespace was moved to another interface), the hash of `<interface>#1`, `#2` and so on is used instead. If a namespace for the interface already exists, it is reused: steps 1–2 are skipped, steps 3–5 are done again, and apps already running in it keep their network.
2. A veth pair (`veth0_<hash>` / `veth1_<hash>`) connects the namespace to the host. The namespace gets the subnet `10.0.N.0/24`, the host end gets `10.0.N.1`, the namespace end `10.0.N.2`.
3. On the host, `net.ipv4.ip_forward` is enabled, a `MASQUERADE` rule for the subnet on the selected interface is added, together with two `FORWARD` rules that allow traffic only between this veth and this interface. All rules carry the comment `intermux:ns_<hash>`.
4. Policy routing: packets coming from the namespace veth get their own routing table `10000 + N` with a default route through the selected interface, selected by the rule `ip rule from 10.0.N.0/24 iif veth0_<hash>` with priority `500 + N`. Without it the traffic would leave through the host's default route. If the interface has a gateway, the route goes through it (`via <gateway>`); point-to-point interfaces without a gateway (WireGuard, some OpenVPN setups, PPP) get a route straight into the interface (`dev <interface>`). The same table always holds a fallback `unreachable default` route with metric 4096: if the interface goes away (VPN disconnected, Wi-Fi lost), the kernel removes its route and the namespace traffic hits the fallback instead of leaving through the host's default route.
5. The namespace DNS servers are written to `/etc/netns/ns_<hash>/resolv.conf`: the ones you chose or picked automatically (see [DNS](#dns)).
6. The application is started with `ip netns exec ... sudo -u <user> env -i ...`, that is as your regular user, not as root, and with the environment of your desktop session: the one KDE, GNOME and others give to apps they start themselves (`systemctl --user show-environment`; without systemd, the environment of one of your graphical processes). So the app sees your profile, display, audio, D-Bus and portals, and nothing of `sudo` leaks into it. `TMPDIR` points to a separate directory under `/run/user/<uid>`, so apps in different namespaces do not find each other through IPC sockets.

Root is needed only for the network setup (steps 1–5).

What each namespace serves (interface, route, DNS, running apps) is recorded in `/run/intermux/ns_<hash>.json`. Like the namespaces themselves, these files are gone after a reboot.

## Requirements

- Linux with network namespace support (`CONFIG_NET_NS`, enabled in all common distributions)
- Python 3 with the `tkinter` module (only for the GUI)
- `iproute2` with `ip -j` support (including `tc`), `iptables`, `sudo`
- `pkexec` (polkit) to elevate the GUI; `sudo` is used without it
- `xhost` so that the GUI running as root can access the X server
- X11, or Wayland with XWayland (the interface is built with Tk)

No third-party Python packages are needed: the code uses only the standard library.

### Installing dependencies

Debian / Ubuntu / Mint:

```bash
sudo apt install python3 python3-tk iproute2 iptables sudo pkexec x11-xserver-utils
```

On older Debian/Ubuntu releases use the `policykit-1` package instead of `pkexec`.

Arch / Manjaro / EndeavourOS:

```bash
sudo pacman -S python tk iproute2 iptables sudo polkit xorg-xhost
```

Fedora / RHEL / Rocky:

```bash
sudo dnf install python3 python3-tkinter iproute iptables sudo polkit xhost
```

openSUSE:

```bash
sudo zypper install python3 python3-tk iproute2 iptables sudo polkit xhost
```

### Getting the source

```bash
git clone https://github.com/Exordio/intermux.git
cd intermux
python3 -m intermux check
```

`check` lists missing system tools and how to install them.

All commands are run from the repository root. If you use a venv, its Python must be built with `tkinter`.

### Installing into the system

```bash
sudo ./install.sh
```

The script installs from the current checkout:

- the code to `/opt/intermux`, owned by root: the GUI runs as root, so the code it runs must not be writable by a regular user;
- the `intermux` (CLI) and `intermux-gui` commands to `/usr/local/bin`;
- the InterMux entry to the application menu (`/usr/local/share/applications/intermux.desktop`) and its icon to `/usr/local/share/icons/hicolor`.

After that start the GUI from the application menu or with `intermux-gui`, and use `intermux` instead of `python3 -m intermux` (for example, `sudo intermux assign --app firefox --iface wlan0`). Started from the menu, the GUI asks for the password through polkit (`pkexec`), which KDE, GNOME and other desktops provide; without `pkexec` it has to be started from a terminal, where `sudo` can ask for the password.

To update, pull the changes and run `sudo ./install.sh` again. To remove, run `sudo ./install.sh --uninstall`; per-user history and app logs in `~/.local/share/intermux` are kept. `PREFIX` (default `/usr/local`) and `TARGET` (default `/opt/intermux`) can be overridden from the environment.

## Usage

### GUI

```bash
python3 -m intermux.gui
```

Start it as a regular user: it restarts itself as root through `pkexec`, or through `sudo` if `pkexec` is missing.

Workflow:

1. Pick an interface. The list contains only interfaces that are up and have an IPv4 address. "Refresh" updates it.
2. Enter a command name from `PATH` (for example, `firefox`) or the full path to an executable. The drop-down list holds the last 20 apps started successfully; picking one also restores the DNS it was started with. The history is kept in `~/.local/share/intermux/history.json` of your user.
3. Choose DNS: `Auto`, one of the presets (Cloudflare, Google, Quad9), or type your own servers separated by commas. Press "Add" or Enter.
4. Press "Assign" to start every application in the Pending table.

The Pending table shows what will happen on start: which namespace will serve the app and its subnet, whether the namespace already exists (`existing`) or will be created (`new`), and which DNS servers it will get.

The Active table shows the existing namespaces: connection state, interface, route, DNS (marked `auto` when picked automatically), traffic (downloaded and uploaded since the namespace was created, and the current rate) and the bandwidth limit. The apps running in each namespace are listed under it with their PIDs. The table refreshes every 2 seconds.

Traffic is read from the counters of the host end of the veth pair (`ip -s link`), which everything the namespace sends or receives passes through. It is the traffic of all apps in the namespace together and is not split per app.

Connection states:

- `connected` — traffic goes through the interface.
- `interface down`, `interface missing` — the interface is down or gone. Apps in the namespace have no network; traffic does not go around the interface.
- `no route` — the interface exists, but the namespace table has no route through it. This happens when the interface comes back after a disconnect. While the GUI is open, such namespaces are reconnected automatically on the next refresh. Without the GUI, use `reconnect`.

Buttons:

- "Clear" empties the Pending table. Nothing on the system changes.
- "Stop" stops the selected app: `SIGTERM`, then `SIGKILL` after 5 seconds for whatever did not exit, then `SIGKILL` for child processes left behind. With a namespace selected, everything running in it is stopped, including processes not started through InterMux.
- "Kill" does the same with `SIGKILL` right away.
- "Restart" stops the app and starts it again in the same namespace with the same options (for example, a separate Firefox profile). With a namespace selected, all its apps are restarted.
- "Remove namespace" stops everything in the namespace and removes it together with its rules and routes.
- "Move to interface" routes the selected namespace through the interface selected at the top of the window. Apps keep running; their open connections break and are re-established through the new interface. Auto DNS is picked again for the new interface, DNS set by hand is kept.
- "Set DNS" applies the value of the DNS field to the selected namespace.
- "Set limit" limits the bandwidth of the selected namespace to the values in the down and up fields (Mbit/s). An empty field removes the limit.
- "Reset Everything" removes everything InterMux created: namespaces, veth pairs, policy routing rules and their tables, `iptables` rules with the `intermux:` comment, the `/etc/netns/ns_*` directories and `/run/intermux`.

If the app is already running, you are asked whether to close it and start it again through the selected interface, open a second instance with a separate profile, or cancel.

### CLI

`list`, `check` and `status` work without root; the other commands need root.

```bash
# Interfaces that can be used, with addresses and gateways
python3 -m intermux list

# Start an application through an interface
sudo python3 -m intermux assign --app firefox --iface wlan0

# The same with your own DNS servers
sudo python3 -m intermux assign --app firefox --iface wlan0 --dns 9.9.9.9,149.112.112.112

# Existing namespaces: state, interface, subnet, route, DNS, traffic, running apps with PIDs
python3 -m intermux status

# Limit the bandwidth of the wlan0 namespace, Mbit/s (without --down and --up the limits are removed)
sudo python3 -m intermux limit --iface wlan0 --down 20 --up 5

# Move the wlan0 namespace to tun0 without stopping its apps
sudo python3 -m intermux move --iface wlan0 --to tun0

# Stop an app (--kill sends SIGKILL right away), restart it in the same namespace
sudo python3 -m intermux stop firefox
sudo python3 -m intermux restart firefox --iface wlan0

# Stop everything in the wlan0 namespace and remove it
sudo python3 -m intermux remove --iface wlan0

# Change DNS of the wlan0 namespace (or go back to automatic selection: auto)
sudo python3 -m intermux dns --iface wlan0 1.1.1.1,1.0.0.1

# Check system dependencies
python3 -m intermux check

# Reconnect namespaces whose interface is available again (for example, after a VPN reconnect)
sudo python3 -m intermux reconnect

# Remove everything InterMux created (same as "Reset Everything" in the GUI)
sudo python3 -m intermux reset
```

If the app is already running, `assign` asks what to do:

```
firefox is already running (PID 12345).
  1) Close it and start again on the selected network (default profile)
  2) Start a second instance with a separate profile
  3) Cancel
Choice [1/2/3]:
```

### DNS

DNS is set per namespace, that is for all apps started through one interface.

- **Auto.** The interface's own DNS servers from `resolvectl dns <interface>` are used. If there are none (for example, without `systemd-resolved`), the system ones from `resolvectl dns` or `/etc/resolv.conf` are used, except servers in the local networks of other interfaces: the Wi-Fi router is unreachable from a namespace whose traffic goes through a VPN. If no server is left, `1.1.1.1` and `8.8.8.8` are used.
- **A preset or your own list.** IPv4 addresses only, separated by commas or spaces.

Local resolvers (`127.0.0.53` of `systemd-resolved`, dnsmasq and the like) are unreachable from inside a namespace; link-local and IPv6 addresses are not used either.

When an app is assigned to an existing namespace with `Auto` (or without `--dns` in the CLI), its DNS stays as it is. Servers given explicitly replace the current ones.

`resolv.conf` is rewritten in place, so a DNS change also applies to apps that are already running. Apps with their own cache or DNS-over-HTTPS (for example, Firefox with DoH enabled) may keep using the old servers or not use these servers at all.

### Bandwidth limits

A limit applies to the whole namespace, that is to all apps started through one interface. Download is limited on the host end of the veth pair, upload on the end inside the namespace (`tc qdisc ... tbf`). The limit is kept when new apps are assigned to the same interface and disappears together with the namespace.

### Which interfaces are available

Interfaces that cannot lead outside the machine are hidden:

- `veth*` — veth pairs, including the ones InterMux creates. Routing an app through them would loop the traffic.
- `docker*`, `br-*`, `virbr*`, `vboxnet*`, `vmnet*` — Docker, libvirt, VirtualBox and VMware bridges. They connect the host to containers and virtual machines and have no route outside.

The filter works by name prefix; `list` in the CLI uses the same list. To hide or show other interfaces, edit `VIRTUAL_PREFIXES` in `intermux/net/interfaces.py`.

### Wayland

The InterMux window itself is a Tk app and runs through XWayland. Apps started through it get the full session environment, including `WAYLAND_DISPLAY` and `XDG_SESSION_TYPE=wayland`, so native Wayland apps work, and screen sharing goes through xdg-desktop-portal and PipeWire just as for apps started from the desktop.

Unix sockets with a file path (the Wayland, X11, D-Bus and PipeWire sockets in `/run/user/<uid>` and `/tmp/.X11-unix`) work from inside a namespace. Abstract unix sockets belong to a network namespace and do not: an app that reaches a service only through an abstract socket (for example, a D-Bus address of the form `unix:abstract=...`) will not reach it.

### VPN

`tun*`, `tap*`, `wg*` and `ppp*` interfaces are shown with the VPN type. You can route a single app through them without turning on the VPN for the whole system. It does not matter whether the system's own default route goes through the VPN.

If the VPN client sets a route through a gateway (`default via 10.8.0.1 dev tun0`), that gateway is used. WireGuard and other point-to-point interfaces have no gateway; the route in the namespace table then goes straight into the interface.

## Firefox

- If Firefox is not running, or you chose "close and reopen", your default profile is used.
- If you chose a second instance, a separate persistent profile `~/.mozilla/firefox/intermux-<interface>` is created. Bookmarks, cookies and extensions of the default profile are not available in it.
- "Close and reopen" sends `SIGTERM` to your processes named like the app or like the file its symlink points to (case-insensitive), waits up to 5 seconds and kills what is left with `SIGKILL`.

## Limitations

- **IPv4 only.** Forwarding and NAT are set up for IPv4 only; there is no IPv6 in the namespace.
- **A gateway or a point-to-point interface is required.** If a regular interface (Ethernet, Wi-Fi) has no gateway in the main routing table, the namespace has no network (state `no route`).
- **Moving to another interface and `conntrack`.** So that open UDP flows do not keep using the old interface's address, conntrack entries of the namespace subnet are dropped on a move. This needs the `conntrack` tool (package `conntrack-tools` on Arch and Fedora, `conntrack` on Debian/Ubuntu). Without it such flows recover only when their conntrack entries expire.
- **One set of DNS servers per interface.** All apps started through one interface run in one namespace and use the same DNS servers.
- `net.ipv4.ip_forward` stays enabled after a reset: other software (Docker, libvirt) may rely on it.
- **Chromium** is blocked in the code: according to the original author, its sandbox conflicts with network namespaces. Other Chromium-based browsers (Chrome, Brave and so on) are not blocked, but have not been tested.
- **A VPN with a kill switch** (`iptables`/`nftables` rules that block traffic outside the tunnel) may block namespace traffic through other interfaces. This is a setting of the VPN client; InterMux does not change it.
- A namespace isolates only the network. Files, processes and user permissions are shared with the system, so it is not a security boundary.

## Project layout

```
install.sh              # System installation, see above
packaging/
└── intermux.desktop    # Application menu entry
intermux/
├── __main__.py         # python3 -m intermux → cli.main()
├── cli.py              # Command line interface
├── binding.py          # Flows shared by CLI and GUI: checks, namespace, launch, app control
├── log.py              # Logging setup
├── system/
│   ├── shell.py        # Running commands, paths to ip/iptables/sysctl
│   ├── users.py        # The real user behind sudo/pkexec
│   ├── session.py      # Graphical session environment, xhost
│   ├── privileges.py   # Restarting as root
│   └── deps.py         # System dependency check
├── net/
│   ├── interfaces.py   # Interfaces and gateways via ip -j
│   ├── dns.py          # DNS servers for namespaces: auto selection, presets, input parsing
│   ├── namespace.py    # Creating, reusing, moving, removing and resetting namespaces
│   ├── registry.py     # What each namespace serves (/run/intermux)
│   ├── shaping.py      # Bandwidth limits with tc
│   └── traffic.py      # Namespace traffic counters
├── apps/
│   ├── launcher.py     # Starting an app in a namespace as the user
│   ├── processes.py    # Finding and stopping running instances, processes of a namespace
│   └── firefox.py      # Firefox flags, profiles and lock files
└── gui/
    ├── __main__.py     # python3 -m intermux.gui
    ├── app.py          # Main window
    ├── dialogs.py      # "Application is running" dialog
    ├── history.py      # Recently started apps for the App / Path field
    ├── icons/          # Application icon, 32 to 512 px
    └── theme.py        # Tk colors and styles
```

## Configuration

Routing table numbers and rule priorities are set in `intermux/net/namespace.py`:

```python
TABLE_BASE = 10000   # namespace table = TABLE_BASE + N (10001–10253)
PRIORITY_BASE = 500  # ip rule priority = PRIORITY_BASE + N (501–753)
```

## Troubleshooting

The CLI and the GUI write a detailed log (DEBUG level, every executed command, stack traces) to `~/.local/share/intermux/intermux.log` of the user the process runs as. After elevation this is usually root, so `/root/.local/share/intermux/intermux.log`.

The output of every app started through InterMux goes to `~/.local/share/intermux/apps/<app>.log` of your user; the file is overwritten on every start. Apps do not write to the terminal InterMux runs in, so closing InterMux or its terminal does not affect them.

If an interface is not listed, check that it is up and has an IPv4 address:

```bash
ip addr show
sudo ip link set <interface> up
```

If an app has no internet access:

```bash
python3 -m intermux check
python3 -m intermux status               # namespace state, interface, route and DNS
ip route show table <10000 + N>          # route through the interface and the unreachable fallback
sysctl net.ipv4.ip_forward               # must be 1
sudo iptables -t nat -S POSTROUTING      # MASQUERADE rule for 10.0.N.0/24
ip rule show                             # rule from 10.0.N.0/24 iif veth0_<hash>
sudo ip netns exec ns_<hash> ping -c1 1.1.1.1
cat /etc/netns/ns_<hash>/resolv.conf
```

If the GUI does not start on Wayland, make sure XWayland is installed (`xorg-xwayland` on Arch, `xwayland` on Debian/Ubuntu).

Early InterMux versions registered `<interface>_rt` tables in `rt_tables`. They had no effect on namespace traffic and are no longer created. `reset` removes them together with their rules.

## License

MIT, see [LICENSE](LICENSE). Original project: Rishi Bhati, 2025. Changes in this fork: Exord, 2026.
