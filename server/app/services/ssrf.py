"""HandoffRail API Server — SSRF protection utilities.

Blocks webhook and callback URLs that point to private/internal networks
to prevent Server-Side Request Forgery attacks.

Blocked ranges:
- Loopback: 127.0.0.0/8, ::1
- Private: 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, fc00::/7
- Link-local: 169.254.0.0/16 (cloud metadata endpoints), fe80::/10
- Unspecified: 0.0.0.0, ::
- Broadcast: 255.255.255.255

Allows override via HR_ALLOWED_WEBHOOK_HOSTS env var (comma-separated hostnames).
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse

# Blocked IP ranges
BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback IPv4
    ipaddress.ip_network("10.0.0.0/8"),        # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),     # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),    # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),    # Link-local (cloud metadata)
    ipaddress.ip_network("0.0.0.0/8"),         # Unspecified
    ipaddress.ip_network("255.255.255.255/32"),  # Broadcast
    ipaddress.ip_network("::1/128"),           # Loopback IPv6
    ipaddress.ip_network("fc00::/7"),          # Unique local IPv6
    ipaddress.ip_network("fe80::/10"),         # Link-local IPv6
    ipaddress.ip_network("::/128"),            # Unspecified IPv6
]

# Hostnames that are always blocked
BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",  # GCP metadata
    "metadata",                  # GCP metadata alias
    "169.254.169.254",          # AWS/Azure metadata
}

# Allow override via env var
_ALLOWED_HOSTS = os.environ.get("HR_ALLOWED_WEBHOOK_HOSTS", "")
ALLOWED_HOSTS = {h.strip().lower() for h in _ALLOWED_HOSTS.split(",") if h.strip()}


def _resolve_hostname(hostname: str) -> list[str]:
    """Resolve a hostname to IP addresses. Returns list of IP strings."""
    try:
        # Use getaddrinfo for dual-stack resolution
        results = socket.getaddrinfo(hostname, None)
        return [r[4][0] for r in results]
    except socket.gaierror:
        return []


def _is_ip_blocked(ip_str: str) -> bool:
    """Check if an IP address is in a blocked range."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # Invalid IP — block by default

    for network in BLOCKED_NETWORKS:
        if ip in network:
            return True
    return False


def is_url_safe(url: str) -> tuple[bool, str]:
    """Check if a URL is safe from SSRF attacks.

    Args:
        url: The URL to validate.

    Returns:
        Tuple of (is_safe, reason). If is_safe is False, reason explains why.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "Invalid URL format"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL must have a hostname"

    hostname_lower = hostname.lower()

    # Check allowlist first (overrides blocklist)
    if hostname_lower in ALLOWED_HOSTS:
        return True, "Host is in allowlist"

    # Check blocked hostnames
    if hostname_lower in BLOCKED_HOSTNAMES:
        return False, f"Hostname '{hostname}' is blocked (internal/metadata endpoint)"

    # If hostname is already an IP, check directly
    try:
        ipaddress.ip_address(hostname)
        if _is_ip_blocked(hostname):
            return False, f"IP address {hostname} is in a blocked range"
        return True, "IP address is allowed"
    except ValueError:
        pass

    # Resolve hostname and check all resolved IPs
    resolved_ips = _resolve_hostname(hostname)
    if not resolved_ips:
        # Can't resolve — allow but log (could be a valid hostname that's temporarily unresolvable)
        return True, "Hostname could not be resolved (allowed with caution)"

    for ip_str in resolved_ips:
        if _is_ip_blocked(ip_str):
            return False, f"Hostname '{hostname}' resolves to blocked IP {ip_str}"

    return True, "URL is safe"
