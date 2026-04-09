"""Tests for scrapy.core.downloader.handlers._httpx.HttpxDownloadHandler."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

import pytest
from scrapy import Request

from tests.test_handlers_base import (
    TestHttp11Base,
    TestHttpProxyBase,
    TestHttps11Base,
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


pytest.importorskip("niquests")


class NiquestsDownloadHandlerMixin:
    @property
    def download_handler_cls(self) -> type[DownloadHandlerProtocol]:
        from scrapy_download_handlers_incubator import (  # noqa: PLC0415
            NiquestsDownloadHandler,
        )

        return NiquestsDownloadHandler


class TestHttp11(NiquestsDownloadHandlerMixin, TestHttp11Base):
    handler_merges_headers = True

    @coroutine_test
    async def test_unsupported_bindaddress(
        self, caplog: pytest.LogCaptureFixture, mockserver: MockServer
    ) -> None:
        meta = {"bindaddress": ("127.0.0.2", 0)}
        request = Request(mockserver.url("/text"), meta=meta)
        async with self.get_dh() as download_handler:
            response = await download_handler.download_request(request)
        assert response.body == b"Works"
        assert (
            "The 'bindaddress' request meta key is not supported by NiquestsDownloadHandler"
            in caplog.text
        )

    # skip macOS tests
    @pytest.mark.skipif(
        sys.platform == "darwin",
        reason="127.0.0.2 is not available on macOS by default",
    )
    @coroutine_test
    async def test_bind_address_port_warning(
        self, caplog: pytest.LogCaptureFixture, mockserver: MockServer
    ) -> None:
        request = Request(mockserver.url("/client-ip"))
        async with self.get_dh(
            {"DOWNLOAD_BIND_ADDRESS": ("127.0.0.2", 12345)}
        ) as download_handler:
            response = await download_handler.download_request(request)
        assert response.body == b"127.0.0.2"
        assert "DOWNLOAD_BIND_ADDRESS specifies a port (12345)" in caplog.text
        assert "Ignoring the port" in caplog.text

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
            "The 'proxy' request meta key is not supported by NiquestsDownloadHandler"
            in caplog.text
        )


class TestHttps11(NiquestsDownloadHandlerMixin, TestHttps11Base):
    handler_merges_headers = True
    tls_log_message = "SSL connection to 127.0.0.1 using protocol TLSv1_3, cipher"


class TestSimpleHttps(NiquestsDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttps11WrongHostname(
    NiquestsDownloadHandlerMixin, TestHttpsWrongHostnameBase
):
    pass


class TestHttps11InvalidDNSId(NiquestsDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttps11InvalidDNSPattern(
    NiquestsDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


# custom ciphers are not supported
# class TestHttps11CustomCiphers


class TestHttp11WithCrawler(TestHttpWithCrawlerBase):
    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_download_handlers_incubator.NiquestsDownloadHandler",
                "https": "scrapy_download_handlers_incubator.NiquestsDownloadHandler",
            }
        }


class TestHttps11WithCrawler(TestHttp11WithCrawler):
    is_secure = True

    @pytest.mark.skip(reason="response.certificate is not implemented")
    @coroutine_test
    async def test_response_ssl_certificate(self, mockserver: MockServer) -> None:
        pass


@pytest.mark.skip(reason="Proxy support is not implemented yet")
class TestHttp11Proxy(NiquestsDownloadHandlerMixin, TestHttpProxyBase):
    pass


@pytest.mark.skip(reason="Proxy support is not implemented yet")
class TestHttps11Proxy(NiquestsDownloadHandlerMixin, TestHttpProxyBase):
    is_secure = True
