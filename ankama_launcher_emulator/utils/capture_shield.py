"""
mitmproxy addon to capture Ankama auth/Shield traffic.

Usage:
    # Basic capture (console mode):
    mitmproxy -s ankama_launcher_emulator/utils/capture_shield.py

    # With SOCKS5 upstream proxy (route traffic through your proxy):
    mitmproxy -s ankama_launcher_emulator/utils/capture_shield.py --mode upstream:socks5://user:pass@host:port

    # Transparent proxy mode:
    mitmproxy -s ankama_launcher_emulator/utils/capture_shield.py --mode transparent

    # Save to file:
    mitmproxy -s ankama_launcher_emulator/utils/capture_shield.py --set capture_file=shield_capture.json

Then route the official Ankama launcher through mitmproxy (port 8080)
using Proxifier or system proxy settings.

Trigger Shield by logging in from a new IP.
All auth.ankama.com and haapi.ankama.com traffic will be logged.
"""

import json
import logging
from datetime import datetime

from mitmproxy import ctx, http

TARGETS = ["haapi.ankama.com", "auth.ankama.com"]

logger = logging.getLogger(__name__)

captures: list[dict] = []


def load(loader):
    loader.add_option(
        name="capture_file",
        typespec=str,
        default="",
        help="Path to save captured flows as JSON",
    )


def response(flow: http.HTTPFlow):
    if not any(t in flow.request.host for t in TARGETS):
        return

    resp = flow.response
    if resp is None:
        return

    entry = {
        "timestamp": datetime.now().isoformat(),
        "request": {
            "method": flow.request.method,
            "url": flow.request.url,
            "headers": dict(flow.request.headers),
            "body": _decode_body(flow.request.content),
        },
        "response": {
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "body": _decode_body(resp.content),
        },
    }

    captures.append(entry)

    # Console output
    ctx.log.info("=" * 70)
    ctx.log.info(f"[{entry['timestamp']}]")
    ctx.log.info(f"{flow.request.method} {flow.request.url}")
    ctx.log.info(f"Request headers: {json.dumps(entry['request']['headers'], indent=2)}")
    if entry["request"]["body"]:
        ctx.log.info(f"Request body: {entry['request']['body']}")
    ctx.log.info(f"Response: {resp.status_code}")
    if entry["response"]["body"]:
        body = entry["response"]["body"]
        if isinstance(body, dict):
            ctx.log.info(f"Response body: {json.dumps(body, indent=2)}")
        else:
            # Truncate long HTML responses
            text = str(body)
            ctx.log.info(f"Response body: {text[:2000]}{'...' if len(text) > 2000 else ''}")
    ctx.log.info("=" * 70)

    # Auto-save if capture_file is set
    capture_file = ctx.options.capture_file
    if capture_file:
        _save(capture_file)


def done():
    capture_file = ctx.options.capture_file
    if capture_file:
        _save(capture_file)
        ctx.log.info(f"Saved {len(captures)} captures to {capture_file}")


def _save(path: str):
    with open(path, "w") as f:
        json.dump(captures, f, indent=2, ensure_ascii=False)


def _decode_body(content: bytes | None):
    if not content:
        return None
    try:
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError):
        try:
            return content.decode("utf-8", errors="replace")
        except Exception:
            return content.hex()
