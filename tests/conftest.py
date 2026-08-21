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
def _mitm_proxies() -> Generator[dict[str, tuple[MitmProxy, str]]]:
    proxies: dict[str, tuple[MitmProxy, str]] = {}
    try:
        yield proxies
    finally:
        for proxy, _url in proxies.values():
            proxy.stop()


@pytest.fixture  # function scope because it modifies os.environ
def proxy_server(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    _mitm_proxies: dict[str, tuple[MitmProxy, str]],
) -> str:
    kind: str = request.param
    if kind not in _mitm_proxies:
        proxy = MitmProxy(mode="socks5" if kind == "socks5" else None)
        _mitm_proxies[kind] = (proxy, proxy.start())
    _, url = _mitm_proxies[kind]
    if kind == "https":
        url = url.replace("http://", "https://")
    monkeypatch.setenv("http_proxy", url)
    monkeypatch.setenv("https_proxy", url)
    return kind


def pytest_configure(config: pytest.Config) -> None:
    # Needed on Windows to switch from proactor to selector for Twisted reactor compatibility.
    set_asyncio_event_loop_policy()
