"""AWS WAF token bypass for auth.ankama.com.

Handles Ankama's rotating WAF challenges (SHA256, HashcashScrypt,
NetworkBandwidth). Dispatches on the canonical `challenge_type` found
inside the base64-decoded `challenge.input` payload, not on the rotating
opaque hash that appears in the top-level `challenge_type` field.

Framework ported from https://github.com/Switch3301/Aws-Waf-Solver.
Ankama-specific constants (AES key, signal name, WAF URL) were
recovered from the Bubble.D3 reference implementation and confirmed
live against auth.ankama.com on 2026-04-20.

Sync API preserved: `get_aws_waf_token(state, proxy_url)` is a thin
wrapper over the async implementation so callers in pkce_auth don't
need to change.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import os
import random
import secrets
import time
import uuid
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import pyscrypt
from rnet import Client, Impersonate, Proxy

logger = logging.getLogger(__name__)


# ── Ankama-specific constants ────────────────────────────────────────────

_WAF_BASE = (
    "https://3f38f7f4f368.83dbb5dc.eu-south-1.token.awswaf.com"
    "/3f38f7f4f368/e1fcfc58118e"
)
_INPUTS_URL = f"{_WAF_BASE}/inputs?client=browser"
_AES_KEY = bytes.fromhex(
    "93d9f6846b629edb2bdc4466af627d998496cb0c08f9cf043de68d6b25aa9693"
)
_SIGNAL_NAME = "KramerAndRio"
_DOMAIN = "auth.ankama.com"
_SITE = "https://auth.ankama.com"


# ── Challenge-type dispatch ──────────────────────────────────────────────

_ENDPOINT = {
    "HashcashScrypt":   "verify",
    "SHA256":           "verify",
    "NetworkBandwidth": "mp_verify",
}

_BWDTH_SIZES = {1: 1024, 2: 10240, 3: 102400, 4: 1048576, 5: 10485760}


# ── Fingerprint pools ────────────────────────────────────────────────────

_GPU_POOL = json.loads((Path(__file__).parent / "webgl.json").read_text())

_PLUGINS = [
    {"name": "PDF Viewer",                "str": "PDF Viewer "},
    {"name": "Chrome PDF Viewer",         "str": "Chrome PDF Viewer "},
    {"name": "Chromium PDF Viewer",       "str": "Chromium PDF Viewer "},
    {"name": "Microsoft Edge PDF Viewer", "str": "Microsoft Edge PDF Viewer "},
    {"name": "WebKit built-in PDF",       "str": "WebKit built-in PDF "},
]
_PLUGIN_STR = "".join(p["str"] for p in _PLUGINS)
_SCREEN = "1920-1080-1080-24-*-*-*"

_MATH = {
    "tan": "-1.4214488238747245",
    "sin":  "0.8178819121159085",
    "cos": "-0.5753861119575491",
}

# Canvas histogram baseline — varied per-call to defeat exact-match detection
_BASE_BINS = [
    14469, 36, 41, 46, 47, 49, 28, 22, 44, 24, 38, 15, 39, 49, 32, 42, 31, 29,
    22, 33, 32, 27, 40, 28, 47, 12, 31, 32, 42, 20, 27, 35, 118, 22, 22, 31,
    22, 13, 27, 26, 27, 17, 27, 33, 15, 29, 29, 30, 33, 32, 27, 38, 31, 16,
    35, 23, 22, 24, 19, 18, 25, 23, 20, 22, 102, 15, 22, 13, 19, 19, 18, 24,
    13, 26, 10, 15, 26, 16, 14, 19, 16, 20, 18, 26, 18, 49, 15, 19, 24, 22,
    19, 17, 15, 20, 21, 22, 103, 27, 50, 38, 55, 31, 496, 25, 19, 15, 25, 24,
    18, 53, 32, 13, 19, 19, 21, 20, 29, 18, 28, 30, 19, 15, 14, 23, 28, 12,
    33, 131, 41, 35, 33, 29, 8, 15, 13, 17, 28, 33, 41, 21, 35, 23, 26, 33,
    19, 20, 74, 34, 12, 24, 15, 20, 19, 71, 20, 9, 20, 18, 22, 84, 20, 19,
    27, 7, 31, 18, 21, 24, 13, 14, 40, 20, 39, 16, 27, 24, 29, 17, 18, 27,
    16, 14, 16, 26, 13, 17, 14, 22, 20, 15, 20, 99, 15, 9, 18, 16, 15, 20,
    31, 13, 28, 35, 27, 48, 52, 48, 33, 47, 32, 47, 42, 13, 28, 21, 25, 26,
    30, 25, 15, 23, 21, 27, 24, 115, 41, 30, 16, 20, 26, 17, 24, 36, 24, 32,
    24, 60, 28, 33, 25, 37, 48, 32, 31, 26, 19, 51, 34, 50, 31, 43, 43, 53,
    76, 57, 50, 13659,
]

_COLLECTORS = [
    ("fp2",          "100",       0.5, 3),
    ("browser",      "101",       0,   1),
    ("capabilities", "102",       2,   8),
    ("gpu",          "103",       3,   12),
    ("dnt",          "104",       0,   1),
    ("math",         "105",       0,   1),
    ("screen",       "106",       0,   1),
    ("navigator",    "107",       0,   1),
    ("auto",         "108",       0,   1),
    ("stealth",      "undefined", 1,   4),
    ("subtle",       "110",       0,   1),
    ("canvas",       "111",       80,  200),
    ("formdetector", "112",       0,   3),
    ("be",           "undefined", 0,   1),
]

_BRANDS = {
    0: '"Not/A)Brand";v="8", "Chromium";v="{v}", "Google Chrome";v="{v}"',
    1: '"Not A(Brand";v="24", "Chromium";v="{v}", "Google Chrome";v="{v}"',
    2: '"Chromium";v="{v}", "Not(A:Brand";v="24", "Google Chrome";v="{v}"',
    3: '"Not:A-Brand";v="8", "Chromium";v="{v}", "Google Chrome";v="{v}"',
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)


def _sec_ch_ua() -> str:
    ver = "137"
    return _BRANDS[int(ver) % 4].replace("{v}", ver)


def _api_headers() -> dict:
    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "cache-control": "no-cache",
        "ect": "4g",
        "origin": _SITE,
        "pragma": "no-cache",
        "priority": "u=1, i",
        "referer": f"{_SITE}/",
        "sec-ch-ua": _sec_ch_ua(),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "cross-site",
        "user-agent": _USER_AGENT,
    }


# ── Crypto ───────────────────────────────────────────────────────────────


def _encode(obj: dict) -> str:
    """Serialize + CRC32-prefix the signal, matching the challenge.js output."""
    raw = json.dumps(obj, separators=(",", ":"))
    crc = binascii.crc32(raw.encode()) & 0xFFFFFFFF
    return f"{crc:08X}#{raw}"


def _encrypt(plaintext: str) -> str:
    iv = os.urandom(12)
    ct = AESGCM(_AES_KEY).encrypt(iv, plaintext.encode(), None)
    tag = ct[-16:]
    enc = ct[:-16]
    return f"{base64.b64encode(iv).decode()}::{tag.hex()}::{enc.hex()}"


# ── Proof-of-work solvers ────────────────────────────────────────────────


def _check_zeros(h: bytes, difficulty: int) -> bool:
    z = 0
    for b in h:
        if b == 0:
            z += 8
            continue
        for i in range(7, -1, -1):
            if (b & (1 << i)) == 0:
                z += 1
            else:
                return z >= difficulty
        break
    return z >= difficulty


def _solve_sha256(challenge_input: str, checksum: str, difficulty: int) -> str:
    base = (challenge_input + checksum).encode()
    n = 0
    while True:
        if _check_zeros(hashlib.sha256(base + str(n).encode()).digest(), difficulty):
            return str(n)
        n += 1


def _solve_hashcash_scrypt(
    challenge_input: str, checksum: str, difficulty: int, memory: int
) -> str:
    combined = challenge_input + checksum
    salt = checksum.encode()
    n = 0
    while True:
        h = pyscrypt.hash(f"{combined}{n}".encode(), salt, memory, 8, 1, 32)
        if _check_zeros(h, difficulty):
            return str(n)
        n += 1


def _solve_bandwidth(difficulty: int) -> str:
    size = _BWDTH_SIZES.get(difficulty, 1024)
    return base64.b64encode(b"\x00" * size).decode()


# ── Signal (browser fingerprint) ─────────────────────────────────────────


def _rand_canvas() -> tuple[int, list[int]]:
    bins = []
    for v in _BASE_BINS:
        if v > 500:
            bins.append(v + random.randint(-200, 200))
        elif v > 80:
            bins.append(v + random.randint(-15, 15))
        else:
            bins.append(max(1, v + random.randint(-3, 3)))
    return random.randint(100_000_000, 999_999_999), bins


def _build_metrics(has_token: bool) -> tuple[list[dict], dict[str, int]]:
    def r(lo: float, hi: float) -> float:
        return round(random.uniform(lo, hi), 1)

    collectors = [(name, mid, r(lo, hi)) for name, mid, lo, hi in _COLLECTORS]
    fp_metrics = {name: int(v) for name, _, v in collectors}

    enc    = r(0.5, 3)
    crypt  = r(2, 8)
    coll   = sum(v for _, _, v in collectors)
    acq    = round(coll + enc + crypt + r(2, 6), 1)
    chall  = r(2, 8)
    cookie = r(0.1, 1)
    total  = round(acq + chall + cookie, 1)

    m = [{"name": "2", "value": enc, "unit": "2"}]
    m += [{"name": mid, "value": v, "unit": "2"} for _, mid, v in collectors]
    m += [
        {"name": "3", "value": crypt,                    "unit": "2"},
        {"name": "7", "value": 1 if has_token else 0,    "unit": "4"},
        {"name": "1", "value": acq,                      "unit": "2"},
        {"name": "4", "value": chall,                    "unit": "2"},
        {"name": "5", "value": cookie,                   "unit": "2"},
        {"name": "6", "value": total,                    "unit": "2"},
        {"name": "8", "value": 1,                        "unit": "4"},
    ]
    return m, fp_metrics


def _build_signal(location: str, fp_metrics: dict[str, int]) -> dict:
    now = int(time.time() * 1000)
    gpu = random.choice(_GPU_POOL)
    c_hash, c_bins = _rand_canvas()
    return {
        "metrics":      fp_metrics,
        "start":        now,
        "flashVersion": None,
        "plugins":      _PLUGINS,
        "dupedPlugins": f"{_PLUGIN_STR}||{_SCREEN}",
        "screenInfo":   _SCREEN,
        "referrer":     "",
        "userAgent":    _USER_AGENT,
        "location":     location,
        "webDriver":    False,
        "capabilities": {
            "css": {
                "textShadow": 1, "WebkitTextStroke": 1, "boxShadow": 1,
                "borderRadius": 1, "borderImage": 1, "opacity": 1,
                "transform": 1, "transition": 1,
            },
            "js": {
                "audio": True, "geolocation": True, "localStorage": "supported",
                "touch": False, "video": True, "webWorker": True,
            },
            "elapsed": fp_metrics["capabilities"],
        },
        "gpu":  gpu,
        "dnt":  None,
        "math": _MATH,
        "automation": {
            "wd":      {"properties": {"document": [], "window": [], "navigator": []}},
            "phantom": {"properties": {"window": []}},
        },
        "stealth": {"t1": 0, "t2": 0, "i": 1, "mte": 0, "mtd": False},
        "crypto": {
            "crypto": 1, "subtle": 1,
            "encrypt": True, "decrypt": True, "wrapKey": True, "unwrapKey": True,
            "sign": True, "verify": True, "digest": True,
            "deriveBits": True, "deriveKey": True,
            "getRandomValues": True, "randomUUID": True,
        },
        "canvas": {
            "hash":          c_hash,
            "emailHash":     None,
            "histogramBins": c_bins,
        },
        "formDetected":    False,
        "numForms":        0,
        "numFormElements": 0,
        "be":      {"si": False},
        "end":     now + 1,
        "errors":  [],
        "version": "2.4.0",
        "id":      str(uuid.uuid4()),
    }


# ── Body building ────────────────────────────────────────────────────────


def _verify_body(
    challenge: dict,
    solution: str,
    checksum: str,
    encrypted: str,
    metrics: list[dict],
    existing_token: str | None,
) -> str:
    payload = {
        "challenge":      challenge,
        "solution":       solution,
        "signals":        [{"name": _SIGNAL_NAME, "value": {"Present": encrypted}}],
        "checksum":       checksum,
        "existing_token": existing_token,
        "client":         "Browser",
        "domain":         _DOMAIN,
        "metrics":        metrics,
    }
    return json.dumps(payload, separators=(",", ":"))


def _multipart_body(
    challenge: dict,
    solution_data: str,
    checksum: str,
    encrypted: str,
    metrics: list[dict],
    existing_token: str | None,
) -> tuple[str, str]:
    meta = {
        "challenge":      challenge,
        "solution":       None,
        "signals":        [{"name": _SIGNAL_NAME, "value": {"Present": encrypted}}],
        "checksum":       checksum,
        "existing_token": existing_token,
        "client":         "Browser",
        "domain":         _DOMAIN,
        "metrics":        metrics,
    }
    boundary = "----WebKitFormBoundary" + secrets.token_urlsafe(12)[:16]
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="solution_data"\r\n'
        f"\r\n{solution_data}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="solution_metadata"\r\n'
        f"\r\n{json.dumps(meta, separators=(',', ':'))}\r\n"
        f"--{boundary}--\r\n"
    )
    return body, f"multipart/form-data; boundary={boundary}"


# ── Async solver core ────────────────────────────────────────────────────


def _make_client(proxy_url: str | None) -> Client:
    opts: dict[str, Any] = {"impersonate": Impersonate.Chrome137, "cookie_store": True}
    if proxy_url:
        from ankama_launcher_emulator.utils.proxy import to_socks5h

        opts["proxies"] = [Proxy.all(to_socks5h(proxy_url))]
    return Client(**opts)


async def _solve_once(
    client: Client,
    headers: dict,
    location: str,
    existing_token: str | None,
    inp_latency_ms: float | None,
) -> tuple[str | None, float]:
    """One round. Returns (token_or_None, inputs_latency_ms)."""
    t_inp = time.time()
    resp = await client.get(_INPUTS_URL, headers=headers)
    latency = round((time.time() - t_inp) * 1000, 1)
    inputs = await resp.json()
    challenge = inputs["challenge"]
    decoded = json.loads(base64.b64decode(challenge["input"]))
    ctype  = decoded.get("challenge_type", "")
    diff   = decoded.get("difficulty", 1)
    memory = decoded.get("memory", 128)
    logger.info("[WAF] challenge type=%s difficulty=%d", ctype, diff)

    metrics, fp_metrics = _build_metrics(has_token=existing_token is not None)
    if inp_latency_ms is not None:
        metrics.insert(0, {"name": "0", "value": inp_latency_ms, "unit": "2"})
    signal = _build_signal(location, fp_metrics)
    encoded = _encode(signal)
    checksum, _, _ = encoded.partition("#")
    encrypted = _encrypt(encoded)

    endpoint = _ENDPOINT.get(ctype, "verify")
    if ctype == "NetworkBandwidth":
        sol = _solve_bandwidth(diff)
        body, content_type = _multipart_body(
            challenge, sol, checksum, encrypted, metrics, existing_token
        )
    elif ctype == "HashcashScrypt":
        sol = _solve_hashcash_scrypt(challenge["input"], checksum, diff, memory)
        body = _verify_body(challenge, sol, checksum, encrypted, metrics, existing_token)
        content_type = "text/plain;charset=UTF-8"
    elif ctype == "SHA256":
        sol = _solve_sha256(challenge["input"], checksum, diff)
        body = _verify_body(challenge, sol, checksum, encrypted, metrics, existing_token)
        content_type = "text/plain;charset=UTF-8"
    else:
        logger.warning("[WAF] unsupported challenge_type=%s", ctype)
        return None, latency

    verify_headers = {**headers, "content-type": content_type}
    resp = await client.post(
        f"{_WAF_BASE}/{endpoint}", body=body, headers=verify_headers
    )
    result = await resp.json()
    token = result.get("token")
    return token, latency


async def _get_token_async(state: str, proxy_url: str | None) -> str:
    """Two-round solver. Round 1 gets a token; round 2 refines it (better
    trust score)."""
    logger.info(
        "[WAF] solver start proxy=%s state_len=%d", bool(proxy_url), len(state or ""),
    )
    client = _make_client(proxy_url)
    headers = _api_headers()
    location = (
        f"https://auth.ankama.com/login/ankama/form"
        f"?origin_tracker=https://www.ankama-launcher.com/launcher"
        f"&redirect_uri=zaap://login&state={state}"
    )

    last_error: Exception | None = None
    for attempt in range(5):
        try:
            token, inp_latency = await _solve_once(
                client, headers, location, existing_token=None, inp_latency_ms=None
            )
            if not token:
                logger.warning("[WAF] round 0 returned no token (attempt %d)", attempt + 1)
                continue

            # Round 2 — pass the round-1 token as existing_token. Failure
            # here is non-fatal; the round-1 token is still usable.
            try:
                refined, _ = await _solve_once(
                    client, headers, location, existing_token=token,
                    inp_latency_ms=inp_latency,
                )
                if refined:
                    token = refined
            except Exception as exc:
                logger.warning("[WAF] round 1 failed, using round-0 token: %s", exc)

            logger.info("[WAF] aws-waf-token obtained")
            return token
        except Exception as exc:
            last_error = exc
            logger.warning(
                "[WAF] attempt %d failed type=%s: %s",
                attempt + 1, type(exc).__name__, exc,
                exc_info=True,
            )

    raise RuntimeError(f"AWS WAF bypass failed after 5 attempts: {last_error}")


# ── Public sync API ──────────────────────────────────────────────────────


def get_aws_waf_token(state: str, proxy_url: str | None = None) -> str:
    """Obtain aws-waf-token for auth.ankama.com.

    `state` is the CSRF state extracted from the PKCE auth page HTML — it
    is embedded into the signal's `location` field for authenticity.

    Sync wrapper over the async core. Safe to call from any thread that
    doesn't already own an event loop.
    """
    try:
        return asyncio.run(_get_token_async(state, proxy_url))
    except RuntimeError as exc:
        # If a loop is already running on this thread (unlikely for the
        # current sync pkce_auth flow, but future-proofing), re-run on a
        # dedicated thread with its own loop.
        if "event loop" not in str(exc).lower():
            raise
        import threading

        result: dict[str, Any] = {}

        def runner() -> None:
            try:
                result["token"] = asyncio.run(_get_token_async(state, proxy_url))
            except Exception as inner:
                result["error"] = inner

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        t.join()
        if "error" in result:
            raise result["error"]
        return result["token"]
