from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from scrapy import Request
from scrapy.utils.misc import build_from_crawler
from scrapy.utils.test import get_crawler

from scrapy_download_handlers_incubator import CurlCffiDownloadHandler
from tests.test_handlers_base import (
    TestHttpBase,
    TestHttpProxyBase,
    TestHttpsBase,
    TestHttpsInvalidDNSIdBase,
    TestHttpsInvalidDNSPatternBase,
    TestHttpsTLSVersionBase,
    TestHttpsWrongHostnameBase,
    TestHttpWithCrawlerBase,
    TestMitmProxyBase,
    TestRealWebsiteBase,
    TestSimpleHttpsBase,
)
from tests.utils.decorators import coroutine_test

if TYPE_CHECKING:
    from scrapy.core.downloader.handlers import DownloadHandlerProtocol

    from tests.mockserver.http import MockServer


pytest.importorskip("curl_cffi")


class CurlCffiDownloadHandlerMixin:
    @property
    def download_handler_cls(self) -> type[DownloadHandlerProtocol]:
        return CurlCffiDownloadHandler

    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_download_handlers_incubator.CurlCffiDownloadHandler",
                "https": "scrapy_download_handlers_incubator.CurlCffiDownloadHandler",
            }
        }


class TestHttp(CurlCffiDownloadHandlerMixin, TestHttpBase):
    handler_supports_bindaddress_meta = False
    handler_bad_header_handling = "fail"
    handler_supports_idna_rejected_hostnames = False
    # curl_cffi sends header values as UTF-8
    handler_non_utf8_request_header_handling = "replace"


class TestHttps(CurlCffiDownloadHandlerMixin, TestHttpsBase):
    handler_supports_bindaddress_meta = False
    handler_bad_header_handling = "fail"
    handler_supports_idna_rejected_hostnames = False
    handler_non_utf8_request_header_handling = "replace"
    handler_supports_tls_logging = False
    handler_supports_keylogging = False


class TestHttp2(TestHttps):
    http2 = True

    default_handler_settings: ClassVar[dict[str, Any]] = {
        "CURL_CFFI_HTTP_VERSION": "v2",
    }

    @coroutine_test
    async def test_protocol(self, mockserver: MockServer) -> None:
        request = Request(mockserver.url("/host", is_secure=self.is_secure))
        async with self.get_dh() as download_handler:
            response = await download_handler.download_request(request)
        assert response.protocol == "HTTP/2.0"


class TestSimpleHttps(CurlCffiDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttpsWrongHostname(CurlCffiDownloadHandlerMixin, TestHttpsWrongHostnameBase):
    pass


class TestHttpsInvalidDNSId(CurlCffiDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttpsInvalidDNSPattern(
    CurlCffiDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


# custom ciphers are not supported
# class TestHttpsCustomCiphers
# class TestHttpsDefaultCiphers


class TestHttpsTLSVersion(CurlCffiDownloadHandlerMixin, TestHttpsTLSVersionBase):
    pass


class TestHttpWithCrawler(CurlCffiDownloadHandlerMixin, TestHttpWithCrawlerBase):
    pass


class TestHttpsWithCrawler(TestHttpWithCrawler):
    is_secure = True

    @pytest.mark.skip(reason="response.certificate is not implemented")
    @coroutine_test
    async def test_response_ssl_certificate(self, mockserver: MockServer) -> None:
        pass

    @pytest.mark.skip(reason="response.certificate is not implemented")
    @coroutine_test
    async def test_response_ssl_certificate_empty_body(
        self, mockserver: MockServer
    ) -> None:
        pass


class TestHttpProxy(CurlCffiDownloadHandlerMixin, TestHttpProxyBase):
    expected_http_proxy_request_body = b"http://example.com/"


class TestHttpsProxy(CurlCffiDownloadHandlerMixin, TestHttpProxyBase):
    is_secure = True
    expected_http_proxy_request_body = TestHttpProxy.expected_http_proxy_request_body


class TestMitmProxy(CurlCffiDownloadHandlerMixin, TestMitmProxyBase):
    # HTTP destinations fail with "curl: (27)", HTTPS ones work
    handler_supports_ipv6_destination = False


@pytest.mark.requires_internet
class TestRealWebsite(CurlCffiDownloadHandlerMixin, TestRealWebsiteBase):
    handler_supports_tls_logging = False


@coroutine_test
async def test_proxy_header_sessions() -> None:
    proxy = "http://proxy.example:8080"
    handler = build_from_crawler(CurlCffiDownloadHandler, get_crawler())
    try:
        session = handler._get_session(proxy, (("X-A", "1"),))
        assert session is not handler._session
        assert handler._get_session(proxy, (("X-A", "1"),)) is session
        assert (
            handler._get_session("http://other.example:8080", (("X-A", "1"),))
            is session
        )
        assert handler._get_session(proxy, (("X-A", "2"),)) is not session
        assert handler._get_session(proxy) is handler._session
        assert handler._get_session(None, (("X-A", "1"),)) is handler._session
        assert len(handler._proxy_header_sessions) == 2
    finally:
        await handler.close()


@coroutine_test
async def test_proxy_headers_ignored_for_socks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    proxy = "socks5://proxy.example:1080"
    handler = build_from_crawler(CurlCffiDownloadHandler, get_crawler())
    try:
        with caplog.at_level("WARNING"):
            assert handler._get_session(proxy, (("X-A", "1"),)) is handler._session
            assert handler._get_session(proxy, (("X-A", "1"),)) is handler._session
    finally:
        await handler.close()
    assert caplog.text.count("the SOCKS protocol has no headers") == 1
