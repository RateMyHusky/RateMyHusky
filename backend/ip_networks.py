"""Classifies a client IP as campus, Private Relay, mobile, datacenter, other or unknown.

The rating routes use the type to exempt campus and relay networks from IP burst
checks and to hold ratings that come from datacenter networks. Without the ASN
database every non-campus, non-relay address is "unknown", which never holds.
"""

import bisect
import ipaddress
import os
from array import array
from typing import Callable, Iterable

import maxminddb

NETWORK_TYPES = ("campus", "relay", "mobile", "datacenter", "other", "unknown")

CAMPUS_NETWORKS = ("129.10.0.0/16", "155.33.0.0/16")
CAMPUS_ASN = 156

# US carriers' mobile ASNs, from the public AS pages (bgp.he.net, PeeringDB, ipinfo.io/AS<n>).
# Not re-checked live when this was written: verify against one of those before relying on the list.
MOBILE_ASNS = frozenset({21928, 6167, 22394, 20057})

# ipinfo `as_domain` values for clouds, hosts and VPN egress, from the same public AS pages
# (and not re-checked live either). Relay is checked first, so Private Relay egress on
# Akamai or Cloudflare is still "relay".
DATACENTER_DOMAINS = frozenset({
    "amazon.com", "google.com", "microsoft.com", "digitalocean.com", "linode.com",
    "akamai.com", "ovhcloud.com", "hetzner.com", "vultr.com", "m247.com",
    "datacamp.co.uk", "cloudflare.com", "oracle.com", "leaseweb.com", "contabo.com",
    "scaleway.com",
})

_CAMPUS = tuple(ipaddress.ip_network(n) for n in CAMPUS_NETWORKS)


def _merge(ranges):
    starts, ends = array("Q"), array("Q")
    for lo, hi in sorted(ranges):
        if starts and lo <= ends[-1] + 1:
            ends[-1] = max(ends[-1], hi)
        else:
            starts.append(lo)
            ends.append(hi)
    return starts, ends


def parse_relay_ranges(lines: Iterable[str]) -> tuple[array, array, array, array]:
    """Apple's egress CSV -> merged (v4 starts, v4 ends, v6 starts, v6 ends).

    IPv6 values are the top 64 bits: relay prefixes are /64 or shorter.
    """
    v4, v6 = [], []
    for line in lines:
        try:
            net = ipaddress.ip_network(line.split(",")[0].strip())
        except ValueError:
            continue
        if net.version == 4:
            v4.append((int(net.network_address), int(net.broadcast_address)))
        elif net.prefixlen <= 64:
            v6.append((int(net.network_address) >> 64, int(net.broadcast_address) >> 64))
    return (*_merge(v4), *_merge(v6))


def _in(starts, ends, n):
    i = bisect.bisect_right(starts, n) - 1
    return i >= 0 and n <= ends[i]


class NetworkIndex:
    def __init__(self, asn_lookup: Callable[[str], dict | None] | None, relay: tuple):
        self._asn = asn_lookup
        self._v4s, self._v4e, self._v6s, self._v6e = relay

    def _is_relay(self, ip) -> bool:
        if ip.version == 4:
            return _in(self._v4s, self._v4e, int(ip))
        return _in(self._v6s, self._v6e, int(ip) >> 64)

    def network_type(self, ip: str | None) -> str:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return "unknown"
        if addr.version == 6 and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        try:
            info = self._asn(str(addr)) if self._asn else None
        except Exception:
            info = None
        info = info or {}
        asn = str(info.get("asn") or "")
        asn = int(asn[2:]) if asn[:2] == "AS" and asn[2:].isdigit() else None
        if asn == CAMPUS_ASN or any(addr in net for net in _CAMPUS):
            return "campus"
        if self._is_relay(addr):
            return "relay"
        if self._asn is None:
            return "unknown"
        if asn in MOBILE_ASNS:
            return "mobile"
        if info.get("as_domain") in DATACENTER_DOMAINS:
            return "datacenter"
        return "other"


def load_index(data_dir: str) -> NetworkIndex:
    """Reads ipinfo_lite.mmdb and relay.csv from data_dir; a missing or broken file is treated as absent."""
    asn_lookup = None
    mmdb = os.path.join(data_dir, "ipinfo_lite.mmdb")
    if os.path.exists(mmdb):
        try:
            asn_lookup = maxminddb.open_database(mmdb).get
        except Exception as e:
            print(f"[ip_networks] ipinfo_lite.mmdb unusable: {type(e).__name__}")
    else:
        print("[ip_networks] ipinfo_lite.mmdb missing: network types will be unknown")
    relay = parse_relay_ranges([])
    csv_path = os.path.join(data_dir, "relay.csv")
    if os.path.exists(csv_path):
        try:
            with open(csv_path, encoding="utf-8") as f:
                relay = parse_relay_ranges(f)
        except Exception as e:
            print(f"[ip_networks] relay.csv unusable: {type(e).__name__}")
    else:
        print("[ip_networks] relay.csv missing: Private Relay ranges not loaded")
    return NetworkIndex(asn_lookup, relay)
