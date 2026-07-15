"""Minimal in-memory fixed-window rate limiter.

Process-local (like the Garmin MFA nonce store) — run uvicorn single-worker.
Keyed on the real client IP: behind the Cloudflare tunnel every request shares
one peer address, so we prefer ``CF-Connecting-IP`` and fall back to the socket
address for local dev.

``CF-Connecting-IP`` is only trusted when the direct peer is a loopback/private
address — i.e. the request arrived via the local cloudflared tunnel, which
overwrites the header. Anyone reaching the origin directly from the internet
could spoof a fresh value per request and mint unlimited buckets.
"""
import ipaddress
import threading
import time

from fastapi import Request

_hits: dict[str, list[float]] = {}
_lock = threading.Lock()


def _peer_is_tunnel(host: str) -> bool:
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private


def _client_ip(request: Request) -> str:
    sock_ip = request.client.host if request.client else "unknown"
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip and _peer_is_tunnel(sock_ip):
        return cf_ip
    return sock_ip


def allow(request: Request, *, bucket: str, max_attempts: int, window_s: int) -> bool:
    """Record an attempt and return False if the caller is over the limit."""
    key = f"{bucket}:{_client_ip(request)}"
    now = time.monotonic()
    with _lock:
        recent = [t for t in _hits.get(key, []) if now - t < window_s]
        if len(recent) >= max_attempts:
            _hits[key] = recent  # drop the aged-out entries we filtered
            return False
        recent.append(now)
        _hits[key] = recent
        return True
