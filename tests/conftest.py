from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from scrapy.utils.reactor import set_asyncio_event_loop_policy

from tests.mockserver.http import MockServer

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture(scope="session")
def mockserver() -> Generator[MockServer]:
    with MockServer() as mockserver:
        yield mockserver


def pytest_configure(config):
    # Needed on Windows to switch from proactor to selector for Twisted reactor compatibility.
    set_asyncio_event_loop_policy()
