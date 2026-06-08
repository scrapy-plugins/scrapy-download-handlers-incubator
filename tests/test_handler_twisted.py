from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from scrapy.utils.reactor import is_reactor_installed

from tests.test_handlers_base import (
    TestHttpBase,
    TestHttpProxyBase,
    TestHttpsBase,
    TestHttpsCustomCiphersBase,
    TestHttpsInvalidDNSIdBase,
    TestHttpsInvalidDNSPatternBase,
    TestHttpsWrongHostnameBase,
    TestHttpWithCrawlerBase,
    TestMitmProxyBase,
    TestRealWebsiteBase,
    TestSimpleHttpsBase,
)

if TYPE_CHECKING:
    from scrapy.core.downloader.handlers import DownloadHandlerProtocol


pytestmark = pytest.mark.skipif(
    not is_reactor_installed(),
    reason="TwistedDownloadHandler requires an installed Twisted reactor",
)


class TwistedDownloadHandlerMixin:
    @property
    def download_handler_cls(self) -> type[DownloadHandlerProtocol]:
        from scrapy_download_handlers_incubator import (  # noqa: PLC0415
            TwistedDownloadHandler,
        )

        return TwistedDownloadHandler

    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_download_handlers_incubator.TwistedDownloadHandler",
                "https": "scrapy_download_handlers_incubator.TwistedDownloadHandler",
            }
        }


class TestHttp(TwistedDownloadHandlerMixin, TestHttpBase):
    pass


class TestHttps(TwistedDownloadHandlerMixin, TestHttpsBase):
    pass


class TestSimpleHttps(TwistedDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttpsWrongHostname(TwistedDownloadHandlerMixin, TestHttpsWrongHostnameBase):
    pass


class TestHttpsInvalidDNSId(TwistedDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttpsInvalidDNSPattern(
    TwistedDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


class TestHttpsCustomCiphers(TwistedDownloadHandlerMixin, TestHttpsCustomCiphersBase):
    pass


class TestHttpWithCrawler(TwistedDownloadHandlerMixin, TestHttpWithCrawlerBase):
    pass


class TestHttpsWithCrawler(TestHttpWithCrawler):
    is_secure = True


class TestHttpProxy(TwistedDownloadHandlerMixin, TestHttpProxyBase):
    pass


class TestHttpsProxy(TwistedDownloadHandlerMixin, TestHttpProxyBase):
    is_secure = True

    @property
    def handler_supports_tls_in_tls(self) -> bool:
        return False


class TestMitmProxy(TwistedDownloadHandlerMixin, TestMitmProxyBase):
    handler_supports_socks: bool = False

    @property
    def handler_supports_tls_in_tls(self) -> bool:
        return False


@pytest.mark.requires_internet
class TestRealWebsite(TwistedDownloadHandlerMixin, TestRealWebsiteBase):
    pass
