"""PepperChat Event Setup — the arrival routine in one window.

Run this on Windows BEFORE the four terminals when PepperChat moves to a new
network (a phone hotspot at an event, say):

    py -3.13 windows_scripts\\event_setup.py

It writes the addresses into network.env, which every other script reads, so
there is nothing left to hand-edit. It can also drive Pepper's tablet, but only
once module_commandable.py and dispatcher.py are already running.
"""

import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk
import urllib.error
import urllib.request

import __parentdir  # noqa: F401  (puts the repo root on sys.path)
import net_config

PORTPROXY_SCRIPT = r"C:\Users\nesco\fix_subtitle_portproxy.ps1"
CMD_PORT = 7356
NAOQI_PORT = 9559


def send_cmd(cmd):
    """One UDP datagram to the dispatcher, same wire format as pepper_control."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(cmd.encode("utf-8"), (net_config.wsl_ip(), CMD_PORT))
    finally:
        sock.close()


class EventSetup(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PepperChat Event Setup")
        self.resizable(False, False)

        self.pepper_var = tk.StringVar()
        self.ssid_var = tk.StringVar()
        self.pwd_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready.")
        self.addr_var = tk.StringVar()

        self._build()
        self._load_current()
        self.refresh_addresses()

    # ---------- layout ----------

    def _build(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.Frame(self, padding=12)
        frm.grid(sticky="nsew")

        ttk.Label(frm, text="Pepper IP").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.pepper_var, width=22).grid(
            row=0, column=1, sticky="w", **pad)
        ttk.Button(frm, text="Check", command=self.check_pepper).grid(
            row=0, column=2, sticky="w", **pad)
        ttk.Label(frm, text="(chest button tells you)", foreground="#666").grid(
            row=0, column=3, sticky="w", **pad)

        ttk.Label(frm, text="Hotspot SSID").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.ssid_var, width=22).grid(
            row=1, column=1, columnspan=2, sticky="w", **pad)

        ttk.Label(frm, text="Password").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.pwd_var, width=22, show="*").grid(
            row=2, column=1, columnspan=2, sticky="w", **pad)
        ttk.Label(frm, text="(tablet wifi, saved to .env)", foreground="#666").grid(
            row=2, column=3, sticky="w", **pad)

        ttk.Separator(frm, orient="horizontal").grid(
            row=3, column=0, columnspan=4, sticky="ew", pady=10)

        actions = [
            ("1.  Apply network config", self.apply_config),
            ("2.  Rebind portproxy (admin)", self.rebind_portproxy),
            ("3.  Test subtitle URL", self.test_subtitle_url),
            ("Open wifi menu on tablet", lambda: self.tablet("TABLET_WIFI")),
            ("Back to subtitles", lambda: self.tablet("TABLET_SUBTITLES")),
        ]
        for i, (label, action) in enumerate(actions):
            ttk.Button(frm, text=label, command=action, width=30).grid(
                row=4 + i, column=0, columnspan=2, sticky="w", **pad)

        ttk.Label(
            frm,
            text=("Steps 1-3 are the arrival routine; run them before the four\n"
                  "terminals. The tablet buttons need the dispatcher already up.\n"
                  "Config is read at startup, so changes apply to the NEXT run."),
            foreground="#666", justify="left",
        ).grid(row=4, column=2, rowspan=4, columnspan=2, sticky="nw", **pad)

        ttk.Separator(frm, orient="horizontal").grid(
            row=9, column=0, columnspan=4, sticky="ew", pady=10)

        ttk.Label(frm, textvariable=self.addr_var, font=("Consolas", 9)).grid(
            row=10, column=0, columnspan=3, sticky="w", **pad)
        ttk.Button(frm, text="Refresh", command=self.refresh_addresses).grid(
            row=10, column=3, sticky="e", **pad)
        ttk.Label(frm, textvariable=self.status_var, wraplength=560,
                  justify="left").grid(
            row=11, column=0, columnspan=4, sticky="w", **pad)

    # ---------- helpers ----------

    def _load_current(self):
        self.pepper_var.set(net_config.pepper_ip())
        env = net_config._parse(net_config.ENV_PATH)
        self.ssid_var.set(env.get("TABLET_WIFI_SSID", ""))
        # Password intentionally left blank rather than pre-filled: typing it
        # again is cheaper than risking it on screen at an event.

    def say(self, message):
        self.status_var.set(message)

    def in_background(self, label, work):
        """Run slow work off the UI thread, reporting back on it."""
        self.say(label + "...")

        def run():
            try:
                message = work()
            except Exception as err:
                message = "FAILED: %s" % err
            self.after(0, lambda: self.say(message))
            self.after(0, self.refresh_addresses)

        threading.Thread(target=run, daemon=True).start()

    def refresh_addresses(self):
        parts = ["Pepper  %s" % net_config.pepper_ip()]
        for name, fn in (("Windows", net_config.windows_ip),
                         ("WSL", net_config.wsl_ip)):
            try:
                parts.append("%s  %s" % (name, fn()))
            except Exception:
                parts.append("%s  unset" % name)
        self.addr_var.set("      ".join(parts))

    # ---------- actions ----------

    def check_pepper(self):
        ip = self.pepper_var.get().strip()
        if not ip:
            return self.say("Enter Pepper's IP first (press her chest button).")
        if net_config.is_self_assigned(ip):
            return self.say(
                "%s is self-assigned (169.254.x.x) — Pepper's wifi associated "
                "but got no DHCP lease. Wait a minute and press the chest "
                "button again; see STARTUP.txt." % ip)

        def work():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            try:
                sock.connect((ip, NAOQI_PORT))
                return "NaoQi answered on %s:%d — good to use." % (ip, NAOQI_PORT)
            except OSError as err:
                return ("No answer from %s:%d (%s). Check the IP and that "
                        "Pepper is on this network." % (ip, NAOQI_PORT, err))
            finally:
                sock.close()

        self.in_background("Checking %s" % ip, work)

    def apply_config(self):
        ip = self.pepper_var.get().strip()
        if ip and net_config.is_self_assigned(ip):
            return self.say("Refusing to save a 169.254.x.x address — see Check.")

        written = []
        if ip:
            net_config.write_values({"PEPPER_IP": ip})
            written.append("PEPPER_IP")

        env_updates = {}
        ssid = self.ssid_var.get().strip()
        pwd = self.pwd_var.get()
        if ssid:
            env_updates["TABLET_WIFI_SSID"] = ssid
        if pwd:
            env_updates["TABLET_WIFI_PWD"] = pwd
        if env_updates:
            net_config.write_values(env_updates, path=net_config.ENV_PATH)
            # Name the keys, never the password value.
            written.extend(sorted(env_updates))

        self.refresh_addresses()
        if not written:
            return self.say("Nothing to write — fill in a field first.")
        self.say("Wrote %s. Restart the dispatcher for these to take effect."
                 % ", ".join(written))

    def rebind_portproxy(self):
        def work():
            # netsh portproxy needs elevation, hence RunAs; this pops a UAC
            # prompt. The script detects both addresses and writes them into
            # network.env itself, so just re-read afterwards.
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command",
                 "Start-Process powershell -Verb RunAs -Wait -ArgumentList "
                 "'-NoProfile','-ExecutionPolicy','Bypass','-File','%s'"
                 % PORTPROXY_SCRIPT],
                capture_output=True, text=True)
            if completed.returncode != 0:
                return ("Portproxy script failed: %s"
                        % (completed.stderr.strip() or completed.stdout.strip()
                           or "non-zero exit"))
            return ("Portproxy rebound and network.env updated. "
                    "Now run Test subtitle URL.")

        self.in_background("Running portproxy script (approve the UAC prompt)",
                           work)

    def test_subtitle_url(self):
        try:
            url = net_config.subtitle_url()
        except net_config.NetConfigError:
            return self.say("No WINDOWS_IP yet — run Rebind portproxy first.")

        def work():
            try:
                with urllib.request.urlopen(url, timeout=4) as response:
                    body = response.read(2048)
                if b"<" not in body:
                    return "%s answered but served no HTML." % url
                return ("%s is serving the subtitle page. Pepper's tablet will "
                        "load it. Worth confirming from a phone on this network "
                        "too." % url)
            except (urllib.error.URLError, OSError) as err:
                return ("%s is NOT reachable (%s). This is the white-screen "
                        "cause — rebind the portproxy and check the firewall."
                        % (url, err))

        self.in_background("Fetching %s" % url, work)

    def tablet(self, verb):
        try:
            send_cmd(verb)
        except Exception as err:
            return self.say("Could not reach the dispatcher: %s" % err)
        self.say("Sent %s. Nothing happens unless module_commandable.py and "
                 "dispatcher.py are both running." % verb)


if __name__ == "__main__":
    if not sys.platform.startswith("win"):
        print("event_setup.py is the Windows half — run it with "
              "`py -3.13 windows_scripts\\event_setup.py`.")
    EventSetup().mainloop()
