"""Minimal in-memory fixed-window rate limiter.

Process-local (like the Garmin MFA nonce store) — run uvicorn single-worker.
Keyed on the real client IP: behind the Cloudflare tunnel every request shares
one peer address, so we prefer ``CF-Connecting-IP`` and fall back to the socket
address for local dev.
"""
import threading
import time

from fastapi import Request

_hits: dict[str, list[float]] = {}
_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


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
