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


@pytest.fixture  # function scope because it modifies os.environ
def proxy_server(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Generator[str]:
    kind = request.param
    proxy = MitmProxy(mode="socks5" if kind == "socks5" else None)
    url = proxy.start()
    if kind == "https":
        url = url.replace("http://", "https://")
    monkeypatch.setenv("http_proxy", url)
    monkeypatch.setenv("https_proxy", url)

    try:
        yield kind
    finally:
        proxy.stop()


def pytest_configure(config: pytest.Config) -> None:
    # Needed on Windows to switch from proactor to selector for Twisted reactor compatibility.
    set_asyncio_event_loop_policy()
