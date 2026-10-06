# -*- coding: utf-8 -*-
"""Single source of truth for the IPs that drift when PepperChat changes network.

Imported from BOTH Python 2.7 (module_commandable.py, via the NaoQi SDK) and
Python 3.8 (dispatcher.py and friends) and Python 3.13 (windows_scripts/*), so:
stdlib only, no f-strings, no annotations, no dotenv dependency.

Values come from network.env in this directory. A real environment variable of
the same name wins over the file, so a one-off run can override without editing.

The asymmetry worth knowing: WSL cannot discover the Windows *WiFi* address
(ip route and /etc/resolv.conf both give the NAT gateway), and that WiFi address
is exactly what Pepper's tablet has to reach for subtitles. So WINDOWS_IP=auto
is resolved only on the Windows side, which writes the literal back into
network.env; from WSL, auto is an error with a message saying what to run.
"""

import os
import socket
import subprocess
import sys
import time

CONFIG_NAME = "network.env"
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_NAME)

DEFAULTS = {
    "PEPPER_IP": "",
    "WINDOWS_IP": "auto",
    "WSL_IP": "auto",
    "SUBTITLE_PORT": "8088",
}

# Pepper's tablet reaches the robot head over the internal USB link at this
# address, independent of any WiFi. Verify with ALTabletService against the
# robot before trusting it; override with ROBOT_SETTINGS_URL in network.env.
DEFAULT_ROBOT_SETTINGS_URL = "http://198.18.0.1/"


class NetConfigError(Exception):
    pass


def _quote(value):
    """Quote a value only when leaving it bare would change its meaning.

    dotenv stops an unquoted value at a '#', and trailing spaces are easy to
    lose, so wifi passwords in particular need this.
    """
    value = "%s" % value
    if value and value == value.strip() and not any(
            ch in value for ch in ' \t#\'"'):
        return value
    return '"%s"' % value.replace('\\', '\\\\').replace('"', '\\"')


def _parse(path):
    values = {}
    try:
        f = open(path, "r")
    except IOError:
        return values
    try:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                # Mirror of _quote on the way back out.
                value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            values[key.strip()] = value
    finally:
        f.close()
    return values


def _load():
    """network.env merged under the real environment, under the defaults."""
    values = dict(DEFAULTS)
    values.update(_parse(CONFIG_PATH))
    for key in list(values.keys()):
        override = os.environ.get(key)
        if override:
            values[key] = override
    return values


def _get(key):
    return _load().get(key, "").strip()


def on_windows():
    return sys.platform.startswith("win")


def _local_ip():
    """The address of whichever interface routes outward, on this host.

    Same trick as oai_dialogue/udp.py's get_local_ip() — a throwaway UDP socket
    to a public address so the OS picks a route. Nothing is sent. Duplicated
    rather than imported because udp.py is Python 3 only and imports zmq, and
    this module has to stay importable from Python 2.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def _wsl_ip_from_windows():
    """Ask WSL for its own address, from the Windows side."""
    out = subprocess.check_output(["wsl", "hostname", "-I"])
    if not isinstance(out, str):
        out = out.decode("utf-8", "replace")
    for token in out.split():
        if token and not token.startswith("169.254."):
            return token
    raise NetConfigError(
        "'wsl hostname -I' returned no usable address (got %r). Is WSL running?"
        % out.strip()
    )


def pepper_ip():
    """Pepper's address. Falls back to mDNS, which the docs advise against."""
    value = _get("PEPPER_IP")
    if not value or value == "auto":
        return "pepper.local"
    return value


def wsl_ip():
    value = _get("WSL_IP")
    if value and value != "auto":
        return value
    if on_windows():
        return _wsl_ip_from_windows()
    return _local_ip()


def windows_ip():
    value = _get("WINDOWS_IP")
    if value and value != "auto":
        return value
    if on_windows():
        return _local_ip()
    raise NetConfigError(
        "WINDOWS_IP is 'auto', which cannot be resolved from WSL — the WiFi "
        "address the tablet needs is not visible here, only the NAT gateway.\n"
        "Fix it from Windows, either way writes the real value into %s:\n"
        "  py -3.13 windows_scripts\\event_setup.py   (Rebind portproxy)\n"
        "  powershell -File C:\\Users\\nesco\\fix_subtitle_portproxy.ps1"
        % CONFIG_PATH
    )


def subtitle_port():
    """The port subtitles.py binds to inside WSL, and what the portproxy
    forwards it as externally too — kept as one port, not two, because a
    port-80 external forward was tried and tested (2026-10-06) and found to
    collide with IIS, which Windows already has listening on port 80 on this
    machine: the tablet got IIS's own default page instead of ours.  There
    had been a theory that the tablet's webview refused non-standard ports
    outright, but that was a coincidence of stale config and mid-test
    network switching, not a real restriction — ruled out once the tablet
    was confirmed able to render real content (IIS's page) on port 80, just
    not OUR content."""
    try:
        return int(_get("SUBTITLE_PORT"))
    except ValueError:
        return int(DEFAULTS["SUBTITLE_PORT"])


def subtitle_url():
    """What Pepper's tablet is told to load for the subtitle page."""
    return "http://%s:%d" % (windows_ip(), subtitle_port())


def cache_busted(url):
    """Append a fresh query param so a tablet webview can't serve a cached
    response for this URL instead of actually re-fetching. This exact page
    has genuinely been broken more than once mid-session (stale IP, then a
    malformed-HTTP bug) while the tablet kept loading it — subtitles.py's
    no-cache headers are the other half of this, for whichever of the two
    the tablet's specific WebView actually honours.
    """
    sep = "&" if "?" in url else "?"
    return "%s%st=%d" % (url, sep, time.time())


def robot_settings_url():
    """Pepper's own web config page, as reachable from her tablet."""
    return _get("ROBOT_SETTINGS_URL") or DEFAULT_ROBOT_SETTINGS_URL


def is_self_assigned(ip):
    """169.254.x.x means DHCP never answered — see STARTUP.txt."""
    return bool(ip) and ip.strip().startswith("169.254.")


ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def write_values(updates, path=None):
    """Update keys in a KEY=VALUE file, preserving everything else in it.

    Rewrites existing keys in place and appends any new ones, so comments and
    unrelated keys survive. Defaults to network.env; pass ENV_PATH to edit .env.
    """
    if path is None:
        path = CONFIG_PATH
    lines = []
    if os.path.exists(path):
        f = open(path, "r")
        try:
            lines = f.read().splitlines()
        finally:
            f.close()
    remaining = dict(updates)
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                out.append("%s=%s" % (key, _quote(remaining.pop(key))))
                continue
        out.append(line)
    for key in sorted(remaining.keys()):
        out.append("%s=%s" % (key, _quote(remaining[key])))
    f = open(path, "w")
    try:
        f.write("\n".join(out).rstrip("\n") + "\n")
    finally:
        f.close()


if __name__ == "__main__":
    print("config file : %s (%s)" % (
        CONFIG_PATH, "found" if os.path.exists(CONFIG_PATH) else "MISSING"))
    print("pepper_ip   : %s" % pepper_ip())
    for name in ("wsl_ip", "windows_ip", "subtitle_url"):
        try:
            print("%-12s: %s" % (name, globals()[name]()))
        except Exception as err:
            print("%-12s: unavailable — %s" % (name, err))
    print("robot_settings_url: %s" % robot_settings_url())
