"""Anonymous identity helpers for the no-login student rating form.

Nothing identifying is stored raw. Device tokens, IP addresses and /24 or /64
prefixes are stored only as HMAC-SHA256 outputs keyed with RATING_SECRET: the
FTC's position is that a plain hash isn't anonymization, because the small IPv4
space can be brute-forced back to addresses. Without the key the stored values
can't be reversed or matched against a guessed address, and each kind is hashed
under its own label so an IP hash never equals a network hash of the same text.

The "opened" token is signed at form load and carries the fill start time, whether
this load minted a new device cookie, and the first 16 hex characters of the device
hash. Binding it to the device means a token can't be replayed from another
browser to fake a plausible fill time, and the signature stops a client editing
the start time.
"""

import hashlib
import hmac
import ipaddress
import re
import secrets

DEVICE_COOKIE = "rmh_device"
DEVICE_MAX_AGE = 400 * 86400  # Chrome's cap on cookie lifetime

_DEVICE_RE = re.compile(r"^[0-9a-f]{32}$")
_SIG_RE = re.compile(r"^[0-9a-f]{64}$")


def new_device_token():
    return secrets.token_hex(16)


def valid_device_token(value):
    return isinstance(value, str) and _DEVICE_RE.fullmatch(value) is not None


def keyed_hash(secret, kind, value):
    return hmac.new(secret.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()


def ip_prefix(ip):
    """The /24 (IPv4) or /64 (IPv6) network containing ip, or None if unparseable."""
    try:
        addr = ipaddress.ip_address(ip)
        bits = 24 if addr.version == 4 else 64
        return str(ipaddress.ip_network(f"{addr}/{bits}", strict=False))
    except ValueError:
        return None


def _opened_payload(opened_at, device_hash, minted):
    return f"{opened_at}.{int(minted)}.{device_hash[:16]}"


def sign_opened(secret, opened_at, device_hash, minted):
    payload = _opened_payload(opened_at, device_hash, minted)
    return f"{payload}.{keyed_hash(secret, 'opened', payload)}"


def read_opened(secret, token, device_hash, now):
    """(fill_seconds, minted) for a valid token, else (None, False)."""
    if not isinstance(token, str):
        return None, False
    parts = token.split(".")
    if len(parts) != 4:
        return None, False
    try:
        opened_at, minted = int(parts[0]), int(parts[1])
    except ValueError:
        return None, False
    if minted not in (0, 1) or parts[2] != device_hash[:16] or not _SIG_RE.fullmatch(parts[3]):
        return None, False
    expected = keyed_hash(secret, "opened", _opened_payload(opened_at, device_hash, bool(minted)))
    if not hmac.compare_digest(expected, parts[3]):
        return None, False
    return now - opened_at, bool(minted)
