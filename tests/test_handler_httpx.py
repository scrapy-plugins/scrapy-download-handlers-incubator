from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, ClassVar

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
    TestMitmProxyBase,
    TestSimpleHttpsBase,
)
from tests.utils.decorators import coroutine_test

if TYPE_CHECKING:
    from scrapy.core.downloader.handlers import DownloadHandlerProtocol

    from tests.mockserver.http import MockServer


pytest.importorskip("httpx")


class HttpxDownloadHandlerMixin:
    @property
    def download_handler_cls(self) -> type[DownloadHandlerProtocol]:
        # the import will fail if httpx is not installed
        from scrapy_download_handlers_incubator import (  # noqa: PLC0415
            HttpxDownloadHandler,
        )

        return HttpxDownloadHandler


class HttpxDownloadHandlerSettingsMixin:
    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_download_handlers_incubator.HttpxDownloadHandler",
                "https": "scrapy_download_handlers_incubator.HttpxDownloadHandler",
            }
        }


class TestHttp11(HttpxDownloadHandlerMixin, TestHttp11Base):
    handler_supports_bindaddress_meta = False

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


class TestHttps11(HttpxDownloadHandlerMixin, TestHttps11Base):
    handler_supports_bindaddress_meta = False
    tls_log_message = "SSL connection to 127.0.0.1 using protocol TLSv1.3, cipher"


class TestHttps2(TestHttps11):
    http2 = True
    handler_supports_http2_dataloss = False

    default_handler_settings: ClassVar[dict[str, Any]] = {
        "HTTPX_HTTP2_ENABLED": True,
    }

    @coroutine_test
    async def test_protocol(self, mockserver: MockServer) -> None:
        request = Request(mockserver.url("/host", is_secure=self.is_secure))
        async with self.get_dh() as download_handler:
            response = await download_handler.download_request(request)
        assert response.protocol == "HTTP/2"


class TestSimpleHttps(HttpxDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttps11WrongHostname(HttpxDownloadHandlerMixin, TestHttpsWrongHostnameBase):
    pass


class TestHttps11InvalidDNSId(HttpxDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttps11InvalidDNSPattern(
    HttpxDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


class TestHttps11CustomCiphers(HttpxDownloadHandlerMixin, TestHttpsCustomCiphersBase):
    pass


class TestHttp11WithCrawler(HttpxDownloadHandlerSettingsMixin, TestHttpWithCrawlerBase):
    pass


class TestHttps11WithCrawler(TestHttp11WithCrawler):
    is_secure = True


class TestHttp11Proxy(HttpxDownloadHandlerMixin, TestHttpProxyBase):
    expected_http_proxy_request_body = b"http://example.com/"


class TestHttps11Proxy(TestHttp11Proxy):
    is_secure = True
    expected_http_proxy_request_body = TestHttp11Proxy.expected_http_proxy_request_body


class TestMitmProxy(HttpxDownloadHandlerSettingsMixin, TestMitmProxyBase):
    pass
