#!/usr/bin/env python3
"""Local fixture-only smoke. Never run against a remote or production target."""
from __future__ import annotations
import re
from urllib.parse import urlsplit
import argparse
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--web", default="http://127.0.0.1:3000")
    args = parser.parse_args()
    parsed = urlsplit(args.web)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("Fixture smoke is restricted to loopback, never a hosted target")
    with httpx.Client(base_url=args.web, timeout=20) as client:
        for path in ["/", "/api/v1/health", "/api/v1/health/ready"]:
            response = client.get(path)
            assert response.status_code == 200, (path, response.status_code)
            print(f"PASS {path}: 200")
        assert client.get("/api/v1/me").status_code == 401
        response = client.post("/api/auth/login", json={"email": "demo@croptwist.local", "password": "croptwist-demo-2026"})
        assert response.status_code == 200, response.status_code
        assert "token" not in response.json() and "refresh_token" not in response.json()
        assert "HttpOnly" in response.headers.get("set-cookie", "")
        assert client.cookies.get("fs_token") and client.cookies.get("fs_refresh")
        assert client.get("/api/v1/me").status_code == 200
        print("PASS login: HttpOnly cookies, no browser JSON tokens, same-origin authenticated API")
        refresh_before = client.cookies.get("fs_refresh")
        response = client.post("/api/auth/refresh")
        assert response.status_code == 200, response.status_code
        assert client.cookies.get("fs_refresh") != refresh_before
        assert client.get("/api/v1/me").status_code == 200
        print("PASS refresh: rotated HttpOnly refresh cookie and valid owned session")
        retained_access = client.cookies.get("fs_token")
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/v1/me").status_code == 401
        assert client.get("/api/v1/me", headers={"Authorization": f"Bearer {retained_access}"}).status_code == 401
        print("PASS logout: session revoked and authenticated API returns 401")
        secure_response = client.post("/api/auth/login", headers={"x-forwarded-proto": "https"}, json={"email": "demo@croptwist.local", "password": "croptwist-demo-2026"})
        assert secure_response.status_code == 200
        cookie_header = secure_response.headers.get("set-cookie", "")
        assert "Secure" in cookie_header and "HttpOnly" in cookie_header
        print("PASS HTTPS-forwarded cookie attributes: Secure; HttpOnly")
        html = client.get("/", headers={"cookie": "NEXT_LOCALE=ar"}).text
        html_tag = re.search(r"<html\b[^>]*>", html)
        assert html_tag and 'lang="ar"' in html_tag.group() and 'dir="rtl"' in html_tag.group()
        print("PASS Arabic locale: html lang=ar dir=rtl; responsive redesign checks still deferred")
        chunk = re.search(r'(?:src|href)="(/_next/static/[^\"]+)"', html)
        assert chunk and client.get(chunk.group(1)).status_code == 200
        print("PASS static Next.js asset served: 200")
    print("LOCAL SMOKE PASSED; not a hosted deployment health check")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
