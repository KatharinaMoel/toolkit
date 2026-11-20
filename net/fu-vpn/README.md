# fu-vpn — FU Berlin VPN on Linux with the browser login, plus a GNOME top bar icon

FU Berlin's VPN (`vpn.fu-berlin.de`, Cisco AnyConnect) logs you in through a web
page (SSO). On Fedora, GNOME's own VPN switch (NetworkManager-openconnect) opened
that page but never received the token. `fu-vpn` skips NetworkManager: it runs
the login with `openconnect` in your browser, then builds the tunnel as root.

| Piece | What it does |
|-------|--------------|
| `fu-vpn` | `up`, `down`, `toggle`, `status` — every step is printed before it runs |
| `fu-vpn.desktop.in` | App icon "FU-VPN": click toggles, right click offers "Trennen" (disconnect) and "Status" |
| `extension/fu-vpn-indicator@toolkit.local` | GNOME Shell extension: VPN icon in the top bar, struck through while off; menu to connect, disconnect, status |
| `networkmanager/50-fu-vpn-mtu` | Optional, only for the NetworkManager route; `fu-vpn` does not need it |
| `install.sh` | Links the script and the extension into your home folder and writes the app icon |

The messages are German; the tool is meant for FU Berlin members.

## Requirements

- `openconnect` (`sudo dnf install openconnect`), `sudo` rights, `curl`
- Firefox as the login browser (see *Findings*)
- For the icons: GNOME Shell 50 or 51, the terminal `ptyxis` (Fedora's default;
  other terminals via `install.sh --terminal`, the top bar menu always uses `ptyxis`),
  `notify-send` for the desktop notifications

## Install

```bash
bash net/fu-vpn/install.sh --dry-run   # shows every step, changes nothing
bash net/fu-vpn/install.sh
```

- `~/.local/bin/fu-vpn` and the extension folder become **symlinks into this
  repository**, so a `git pull` takes effect at once. Run it from your main
  checkout, not from a worktree you will delete.
- Existing files that are not these symlinks are moved to `<file>.pre-toolkit`,
  never deleted. If such a backup already exists, the script stops.
- On Wayland, GNOME only sees a new extension after you log out and in again.
  Then: `gnome-extensions enable fu-vpn-indicator@toolkit.local`.

## Usage

```bash
fu-vpn            # connect: login in Firefox, then the sudo password
fu-vpn status     # tunnel address, and the HTTP code of CHECK_URL if set
fu-vpn down       # disconnect
fu-vpn toggle     # what the icons call
```

Am I really going through the VPN?

```bash
ip route get <address of a host behind the VPN>   # "dev fu-vpn" = through the tunnel
pgrep -a openconnect                               # is the tunnel process running?
journalctl -b -t openconnect                       # the tunnel's log
```

## Configuration

Optional: copy [`example.conf`](example.conf) to `~/.config/fu-vpn/fu-vpn.conf`.
You can set `SERVER`, `USERAGENT`, `BROWSER`, `MTU`, and `CHECK_URL`/`CHECK_NAME`
(a page only reachable through the VPN, e.g. your department's GitLab).
The interface name is fixed to `fu-vpn`, because the top bar icon watches
`/sys/class/net/fu-vpn`.

## How it works

1. **Login as yourself:** `openconnect --authenticate --external-browser=firefox`
   prints `COOKIE`, `CONNECT_URL` and `FINGERPRINT`. The script reads only these
   keys, without `eval`, and checks the URL and fingerprint format, so nothing the
   server sends can run as a command. The cookie is never shown on screen.
2. **Tunnel as root:** `sudo setsid openconnect --cookie-on-stdin --servercert … --background`.
   The cookie goes in on stdin, so it is not in the process list either.
   `setsid` detaches the tunnel from the terminal window.
3. **Lower the MTU** to 1350: `sudo ip link set dev fu-vpn mtu 1350`.

## Findings behind the design

Observed on Fedora with GNOME 50 and 51 in October and November 2026. The
FU's own instructions may have changed since; check
<https://www.mi.fu-berlin.de/w/IT/ServicesLinuxVpn> (recommends openconnect on
Linux) and <https://www.mi.fu-berlin.de/w/IT/ItServicesVPNZEDAT>.

- **MTU black hole:** the server sets the tunnel to MTU 1390, but only packets up
  to about 1384 bytes got through. The TCP connection opens, then the TLS
  handshake and SSH hang. With 1350 everything works.
- **Firefox cannot run as root** in a user session, so `sudo openconnect` with the
  browser login fails. Hence login and tunnel are split.
- **With Chrome as the login browser the token never arrived**, with Firefox it did.
  Inferred from behaviour, not verified.
- **Tunnel died a few seconds after the window closed** — suspected SIGHUP through
  sudo's pseudo terminal (`use_pty`). Starting it with `setsid` fixed it.
- A hanging old `openconnect` keeps the login port busy ("Address already in use");
  end the old process.
- IPv4 goes through the tunnel (full tunnel), **IPv6 does not**.
- The Cisco Secure Client download is not needed.

## After a GNOME upgrade

GNOME switches off extensions whose `metadata.json` does not list the running
version, silently. Check after every GNOME upgrade:

```bash
gnome-extensions info fu-vpn-indicator@toolkit.local | grep State   # OUT OF DATE?
```

If so, add the new version to `shell-version` in
`extension/fu-vpn-indicator@toolkit.local/metadata.json`, then log out and in.

## Tests

```bash
bash net/fu-vpn/test_fu_vpn.sh
```

`openconnect`, `sudo`, `ip`, `curl` and `gnome-extensions` are stubs; no tunnel
is built and nothing outside a temp folder changes. The extension itself has no
automated test — check it by hand after changes.
