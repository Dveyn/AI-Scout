from __future__ import annotations

import ipaddress
import secrets
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from scout.config import Settings, get_settings

SESSION_KEY = "scout_authenticated"


def auth_enabled(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return s.auth_is_required()


def is_public_path(path: str) -> bool:
    return path == "/login" or path.startswith("/static/")


def verify_credentials(username: str, password: str, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    if not s.scout_auth_password:
        return False
    user_ok = secrets.compare_digest(username, s.scout_auth_user)
    pass_ok = secrets.compare_digest(password, s.scout_auth_password)
    return user_ok and pass_ok


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    if request.client:
        return request.client.host
    return ""


def _ip_allowed(ip: str, allowlist: list[str]) -> bool:
    if not allowlist:
        return True
    if not ip:
        return False
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in allowlist:
        entry = entry.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                if addr in ipaddress.ip_network(entry, strict=False):
                    return True
            elif addr == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        allowlist = settings.allowed_ip_list()
        if allowlist:
            ip = _client_ip(request)
            if not _ip_allowed(ip, allowlist):
                if request.url.path.startswith("/api/"):
                    return JSONResponse({"detail": "Forbidden"}, status_code=403)
                return Response("Forbidden", status_code=403)
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        settings = get_settings()
        if not auth_enabled(settings):
            return await call_next(request)

        if is_public_path(request.url.path):
            return await call_next(request)

        if request.session.get(SESSION_KEY):
            return await call_next(request)

        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        return RedirectResponse(url="/login", status_code=303)
