from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scrapy.utils.reactor import set_asyncio_event_loop_policy

from tests.mockserver.http import MockServer
from tests.utils.proxy import MitmProxy

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(scope="session")
def mockserver() -> Generator[MockServer]:
    with MockServer() as mockserver:
        yield mockserver


@pytest.fixture  # function scope because it modifies os.environ
def mitm_proxy_server(monkeypatch: pytest.MonkeyPatch) -> Generator[MitmProxy]:
    proxy = MitmProxy()
    url = proxy.start()
    monkeypatch.setenv("http_proxy", url)
    monkeypatch.setenv("https_proxy", url)

    try:
        yield proxy
    finally:
        proxy.stop()


@pytest.fixture  # function scope because it modifies os.environ
def mitm_proxy_server_https(monkeypatch: pytest.MonkeyPatch) -> Generator[MitmProxy]:
    proxy = MitmProxy()
    url = proxy.start().replace("http://", "https://")
    monkeypatch.setenv("http_proxy", url)
    monkeypatch.setenv("https_proxy", url)

    try:
        yield proxy
    finally:
        proxy.stop()


def pytest_configure(config):
    # Needed on Windows to switch from proactor to selector for Twisted reactor compatibility.
    set_asyncio_event_loop_policy()
