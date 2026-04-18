from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import pytest

from tests.test_handlers_base import (
    TestHttp11Base,
    TestHttpProxyBase,
    TestHttps11Base,
    TestHttpsCustomCiphersBase,
    TestHttpsInvalidDNSIdBase,
    TestHttpsInvalidDNSPatternBase,
    TestHttpsWrongHostnameBase,
    TestHttpWithCrawlerBase,
    TestMitmProxyBase,
    TestSimpleHttpsBase,
)
from tests.utils.decorators import coroutine_test

if TYPE_CHECKING:
    from scrapy.core.downloader.handlers import DownloadHandlerProtocol

    from tests.mockserver.http import MockServer


pytest.importorskip("aiohttp")


class AiohttpDownloadHandlerMixin:
    @property
    def download_handler_cls(self) -> type[DownloadHandlerProtocol]:
        from scrapy_download_handlers_incubator import (  # noqa: PLC0415
            AiohttpDownloadHandler,
        )

        return AiohttpDownloadHandler


HANDLER_IMPORT_NAME = "scrapy_download_handlers_incubator.AiohttpDownloadHandler"


class TestHttp11(AiohttpDownloadHandlerMixin, TestHttp11Base):
    handler_supports_bindaddress_meta = False


class TestHttps11(AiohttpDownloadHandlerMixin, TestHttps11Base):
    handler_supports_bindaddress_meta = False

    @pytest.mark.skip(reason="TLS verbose logging is not available for short responses")
    @coroutine_test
    async def test_tls_logging(
        self, mockserver: MockServer, caplog: pytest.LogCaptureFixture
    ) -> None:
        pass


class TestSimpleHttps(AiohttpDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttps11WrongHostname(AiohttpDownloadHandlerMixin, TestHttpsWrongHostnameBase):
    pass


class TestHttps11InvalidDNSId(AiohttpDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttps11InvalidDNSPattern(
    AiohttpDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


class TestHttps11CustomCiphers(AiohttpDownloadHandlerMixin, TestHttpsCustomCiphersBase):
    pass


class TestHttp11WithCrawler(TestHttpWithCrawlerBase):
    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": HANDLER_IMPORT_NAME,
                "https": HANDLER_IMPORT_NAME,
            }
        }

    @pytest.mark.skip(reason="response.ip_address is not available for short responses")
    @coroutine_test
    async def test_response_ip_address(self, mockserver: MockServer) -> None:
        pass


class TestHttps11WithCrawler(TestHttp11WithCrawler):
    is_secure = True

    @pytest.mark.skip(
        reason="response.certificate is not available for short responses"
    )
    @coroutine_test
    async def test_response_ssl_certificate(self, mockserver: MockServer) -> None:
        pass

    @pytest.mark.skip(reason="response.ip_address is not available for short responses")
    @coroutine_test
    async def test_response_ip_address(self, mockserver: MockServer) -> None:
        pass


class TestHttp11Proxy(AiohttpDownloadHandlerMixin, TestHttpProxyBase):
    pass


class TestHttps11Proxy(AiohttpDownloadHandlerMixin, TestHttpProxyBase):
    is_secure = True

    @staticmethod
    def handler_supports_tls_in_tls() -> bool:
        return sys.version_info >= (3, 11)


class TestMitmProxy(TestMitmProxyBase):
    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": HANDLER_IMPORT_NAME,
                "https": HANDLER_IMPORT_NAME,
            }
        }

    @staticmethod
    def handler_supports_tls_in_tls() -> bool:
        return sys.version_info >= (3, 11)
