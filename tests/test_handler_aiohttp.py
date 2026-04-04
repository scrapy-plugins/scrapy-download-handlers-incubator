"""Tests for scrapy.core.downloader.handlers._aiohttp.AiohttpDownloadHandler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from scrapy import Request

from tests.test_handlers_base import (
    TestHttp11Base,
    TestHttpProxyBase,
    TestHttps11Base,
    TestHttpsCustomCiphersBase,
    TestHttpsInvalidDNSIdBase,
    TestHttpsInvalidDNSPatternBase,
    TestHttpsWrongHostnameBase,
    TestHttpWithCrawlerBase,
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


class TestHttp11(AiohttpDownloadHandlerMixin, TestHttp11Base):
    @coroutine_test
    async def test_unsupported_bindaddress(
        self, caplog: pytest.LogCaptureFixture, mockserver: MockServer
    ) -> None:
        meta = {"bindaddress": "127.0.0.2"}
        request = Request(mockserver.url("/text"), meta=meta)
        async with self.get_dh() as download_handler:
            response = await download_handler.download_request(request)
        assert response.body == b"Works"
        assert (
            "The 'bindaddress' request meta key is not supported by AiohttpDownloadHandler"
            in caplog.text
        )

    @coroutine_test
    async def test_unsupported_proxy(
        self, caplog: pytest.LogCaptureFixture, mockserver: MockServer
    ) -> None:
        meta = {"proxy": "127.0.0.2"}
        request = Request(mockserver.url("/text"), meta=meta)
        async with self.get_dh() as download_handler:
            response = await download_handler.download_request(request)
        assert response.body == b"Works"
        assert (
            "The 'proxy' request meta key is not supported by AiohttpDownloadHandler"
            in caplog.text
        )


class TestHttps11(AiohttpDownloadHandlerMixin, TestHttps11Base):
    @pytest.mark.skip(reason="TLS verbose logging is not implemented")
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
                "http": "scrapy_download_handlers_incubator.AiohttpDownloadHandler",
                "https": "scrapy_download_handlers_incubator.AiohttpDownloadHandler",
            }
        }

    @pytest.mark.skip(reason="response.ip_address is not implemented")
    @coroutine_test
    async def test_response_ip_address(self, mockserver: MockServer) -> None:
        pass


class TestHttps11WithCrawler(TestHttp11WithCrawler):
    is_secure = True

    @pytest.mark.skip(reason="response.certificate is not implemented")
    @coroutine_test
    async def test_response_ssl_certificate(self, mockserver: MockServer) -> None:
        pass

    @pytest.mark.skip(reason="response.ip_address is not implemented")
    @coroutine_test
    async def test_response_ip_address(self, mockserver: MockServer) -> None:
        pass


@pytest.mark.skip(reason="Proxy support is not implemented yet")
class TestHttp11Proxy(AiohttpDownloadHandlerMixin, TestHttpProxyBase):
    pass


@pytest.mark.skip(reason="Proxy support is not implemented yet")
class TestHttps11Proxy(AiohttpDownloadHandlerMixin, TestHttpProxyBase):
    is_secure = True
