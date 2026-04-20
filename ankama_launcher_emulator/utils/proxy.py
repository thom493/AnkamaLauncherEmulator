import logging
from urllib.parse import urlparse

import requests

from ankama_launcher_emulator.proxy.dofus3.proxy_listener import ProxyListener

logger = logging.getLogger()


def to_socks5h(proxy_url: str) -> str:
    """Convert socks5:// to socks5h:// for remote DNS resolution."""
    if proxy_url.startswith("socks5://"):
        return "socks5h://" + proxy_url[len("socks5://") :]
    return proxy_url


def to_http_proxy(proxy_url: str) -> str:
    """Convert socks5:// to http:// (same host:port and creds).

    Chromium does not support SOCKS5 username/password auth, but does
    support HTTP proxy basic auth via QWebEnginePage.proxyAuthenticationRequired.
    Most residential proxy providers expose both schemes on the same port.
    """
    if proxy_url.startswith("socks5h://"):
        return "http://" + proxy_url[len("socks5h://") :]
    if proxy_url.startswith("socks5://"):
        return "http://" + proxy_url[len("socks5://") :]
    return proxy_url


def validation_proxy_url(proxy_url: str | None) -> bool:
    if not proxy_url:
        return True
    return urlparse(proxy_url).scheme == "socks5"


def verify_proxy_ip(proxy_url: str, timeout: int = 10) -> str:
    """Check proxy is reachable and return its exit IP. Raises on failure."""
    session = requests.Session()
    h_url = to_socks5h(proxy_url)
    session.proxies = {"http": h_url, "https": h_url}
    try:
        response = session.get("https://api.ipify.org", timeout=timeout)
        response.raise_for_status()
        exit_ip = response.text.strip()
        logger.info(f"[PROXY] Exit IP: {exit_ip}")
        return exit_ip
    except (requests.RequestException, OSError) as err:
        raise ConnectionError(f"Proxy unreachable or failed: {err}") from err


def get_info_by_proxy_url(proxy_url: str):
    parsed = urlparse(proxy_url)
    if parsed.scheme != "socks5":
        raise ValueError("Invalid proxy url")
    return parsed


def build_proxy_listener(proxy_url: str | None) -> tuple[ProxyListener, str | None]:
    if not proxy_url:
        return ProxyListener(), None
    parsed = get_info_by_proxy_url(proxy_url)
    return (
        ProxyListener(
            socks5_host=parsed.hostname,
            socks5_port=parsed.port,
            socks5_username=parsed.username or None,
            socks5_password=parsed.password or None,
        ),
        proxy_url,
    )
