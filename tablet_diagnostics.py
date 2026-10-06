# -*- coding: utf-8 -*-
"""One-off, read-only diagnostic: what does ALTabletService actually expose
on this robot, beyond the 4 methods this codebase currently uses
(getWifiStatus, configureWifi, loadUrl, showWebview)? Written 2026-10-06
while chasing a case where the tablet's HTTP request never reached a
server confirmed reachable from every other device on the same network --
looking specifically for anything related to the tablet's own IP/network
state, since getWifiStatus() only reports radio association, not whether
the tablet actually has a working IP/gateway/DNS.

Opens its OWN broker -- safe to run alongside the already-running
module_commandable.py, same as NaoQi's own tools do.

Usage:
    python2 tablet_diagnostics.py --pip <pepper_ip>
"""
from optparse import OptionParser
import re
import naoqi
from naoqi import ALProxy

import net_config

parser = OptionParser()
parser.add_option("--pip", dest="pip", help="Pepper's IP address")
parser.add_option("--pport", dest="pport", type="int", default=9559)
parser.set_defaults(pip=net_config.pepper_ip())
(opts, _args) = parser.parse_args()

print("Connecting to %s:%d ..." % (opts.pip, opts.pport))
broker = naoqi.ALBroker("tabletDiagBroker", "0.0.0.0", 0, opts.pip, opts.pport)
tablet = ALProxy("ALTabletService", opts.pip, opts.pport)

methods = sorted(tablet.getMethodList())
print("\n%d methods total on ALTabletService.\n" % len(methods))

interesting = [m for m in methods if re.search(
    r"ip|network|wifi|address|gateway|dns|dhcp|connect", m, re.IGNORECASE)]
print("Methods that look network/IP-related:")
for m in interesting:
    try:
        help_text = tablet.getMethodHelp(m)
        summary = help_text.get("description", "") if isinstance(help_text, dict) else str(help_text)
    except Exception as e:
        summary = "(getMethodHelp failed: %s)" % e
    print("  %-30s %s" % (m, summary.split("\n")[0][:80]))

print("\nCurrent getWifiStatus(): %r" % tablet.getWifiStatus())

print("\n--- Full method list ---")
for m in methods:
    print(" ", m)
