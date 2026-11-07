from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scrapy.utils.reactor import set_asyncio_event_loop_policy

from tests.mockserver.http import MockServer
from tests.mockserver.mitm_proxy import MitmProxy

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(scope="session")
def mockserver() -> Generator[MockServer]:
    with MockServer() as mockserver:
        yield mockserver


@pytest.fixture(scope="session")
def mockserver_ipv6() -> Generator[MockServer]:
    """A mockserver addressed by the IPv6 loopback.

    Tests using this must skip when :func:`ipv6_loopback_available` is False.
    """
    # Where IPv6 sockets also accept IPv4, binding the IPv6 wildcard keeps
    # IPv4 servers from getting the same port numbers. Otherwise a client
    # resolving localhost to ::1 first would reach this server instead of
    # an IPv4 one.
    with MockServer("::") as mockserver:
        yield mockserver


@pytest.fixture(scope="session")
def _mitm_proxies() -> Generator[dict[tuple[str, str], tuple[MitmProxy, str]]]:
    proxies: dict[tuple[str, str], tuple[MitmProxy, str]] = {}
    try:
        yield proxies
    finally:
        for proxy, _url in proxies.values():
            proxy.stop()


@pytest.fixture  # function scope because it modifies os.environ
def proxy_server(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    _mitm_proxies: dict[tuple[str, str], tuple[MitmProxy, str]],
) -> str:
    kind: str = request.param
    # test classes can make the proxy listen on a different address, e.g. "::1"
    host = getattr(request.cls, "proxy_host", "127.0.0.1")
    cache_key = (kind, host)
    if cache_key not in _mitm_proxies:
        proxy = MitmProxy(mode="socks5" if kind == "socks5" else None, host=host)
        _mitm_proxies[cache_key] = (proxy, proxy.start())
    _, url = _mitm_proxies[cache_key]
    if kind == "https":
        url = url.replace("http://", "https://")
    monkeypatch.setenv("http_proxy", url)
    monkeypatch.setenv("https_proxy", url)
    return kind


def pytest_configure(config: pytest.Config) -> None:
    # Needed on Windows to switch from proactor to selector for Twisted reactor compatibility.
    set_asyncio_event_loop_policy()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.get_closest_marker("requires_internet"):
            # Requests to real websites fail every now and then in CI for
            # reasons unrelated to the code under test.
            item.add_marker(pytest.mark.flaky(reruns=2, reruns_delay=5))
