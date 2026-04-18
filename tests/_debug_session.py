"""Verbose request/response logger for the debug harness.

Patches `requests.Session` and `requests.api` so EVERY HTTP call made by
pkce_auth, aws_waf_bypass, shield, etc. is dumped to stdout with full
method/url/headers/body/status/redirect-chain.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

DUMP_DIR = Path(__file__).parent / "debug_dumps"

_RED = "\033[31m"
_GRN = "\033[32m"
_YLW = "\033[33m"
_BLU = "\033[34m"
_DIM = "\033[2m"
_BOLD = "\033[1m"
_END = "\033[0m"


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"{_DIM} ...({len(text) - limit} more chars){_END}"


def _format_headers(headers: dict, indent: str = "    ") -> str:
    if not headers:
        return f"{indent}{_DIM}<none>{_END}"
    lines = []
    for k, v in headers.items():
        if k.lower() in {"cookie", "set-cookie", "authorization", "apikey"}:
            v_str = str(v)
            if len(v_str) > 80:
                v_str = v_str[:80] + f"... ({len(v_str)} chars)"
        else:
            v_str = str(v)
        lines.append(f"{indent}{_DIM}{k}{_END}: {v_str}")
    return "\n".join(lines)


def _format_body(body: Any, content_type: str = "") -> str:
    if body is None:
        return f"    {_DIM}<empty>{_END}"
    if isinstance(body, bytes):
        try:
            body = body.decode("utf-8", errors="replace")
        except Exception:
            return f"    <{len(body)} bytes binary>"
    text = str(body)
    return f"    {_truncate(text, 1500)}"


_call_counter = {"n": 0}


def _log_response(response: requests.Response, *_args, **_kwargs) -> None:
    _call_counter["n"] += 1
    n = _call_counter["n"]
    req = response.request

    color = _GRN if 200 <= response.status_code < 300 else (
        _YLW if 300 <= response.status_code < 400 else _RED
    )

    print()
    print(f"{_BOLD}── HTTP #{n} ─ {_now()} ──────────────────────────────────────{_END}")
    print(f"{_BLU}> {req.method} {req.url}{_END}")
    print(f"{_DIM}  request headers:{_END}")
    print(_format_headers(dict(req.headers), indent="    "))
    if req.body:
        print(f"{_DIM}  request body:{_END}")
        print(_format_body(req.body))

    if response.history:
        print(f"{_DIM}  redirect chain ({len(response.history)} hop(s)):{_END}")
        for h in response.history:
            print(f"    {_YLW}{h.status_code}{_END} {h.url} → {h.headers.get('location', '')}")

    print(f"{color}< HTTP {response.status_code} {response.reason}{_END}  "
          f"({len(response.content)} bytes, {response.elapsed.total_seconds():.2f}s)")
    print(f"{_DIM}  response headers:{_END}")
    print(_format_headers(dict(response.headers), indent="    "))

    ct = response.headers.get("Content-Type", "")
    print(f"{_DIM}  response body:{_END}")
    if "json" in ct:
        try:
            import json
            print(_format_body(json.dumps(response.json(), indent=2)))
        except Exception:
            print(_format_body(response.text))
    elif "html" in ct:
        # HTML can be huge; dump full to file, show snippet
        DUMP_DIR.mkdir(exist_ok=True)
        dump_path = DUMP_DIR / f"resp_{n:03d}_{int(time.time())}.html"
        dump_path.write_text(response.text, encoding="utf-8", errors="replace")
        print(f"    {_DIM}HTML body dumped to {dump_path}{_END}")
        print(_format_body(response.text[:500]))
    else:
        print(_format_body(response.text))


def install_global_hook() -> None:
    """Patch requests.Session.send so all calls are logged.

    Idempotent: calling twice is a no-op.
    """
    if getattr(requests.Session, "_debug_login_hooked", False):
        return

    original_send = requests.Session.send

    def patched_send(self: requests.Session, request, **kwargs):
        # Force verify=False uniformly so we don't add SSL noise to debugging
        response = original_send(self, request, **kwargs)
        try:
            _log_response(response)
        except Exception as exc:
            print(f"{_RED}[debug-session] log hook crashed: {exc}{_END}", file=sys.stderr)
        return response

    requests.Session.send = patched_send  # type: ignore[method-assign]
    requests.Session._debug_login_hooked = True  # type: ignore[attr-defined]


def banner(label: str) -> None:
    print()
    print(f"{_BOLD}{'═' * 60}{_END}")
    print(f"{_BOLD}  {label}{_END}")
    print(f"{_BOLD}{'═' * 60}{_END}")


def step(num: int, total: int, label: str) -> None:
    print()
    print(f"{_BOLD}{_BLU}[{num}/{total}] {label}{_END}")


def ok(msg: str) -> None:
    print(f"  {_GRN}✓ {msg}{_END}")


def fail(msg: str) -> None:
    print(f"  {_RED}✗ {msg}{_END}")


def info(msg: str) -> None:
    print(f"  {_DIM}{msg}{_END}")


def load_dotenv() -> None:
    """Minimal .env loader (no dep on python-dotenv)."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
