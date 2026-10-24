from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from scrapy import Request
from scrapy.exceptions import NotConfigured
from scrapy.http import Headers
from scrapy.utils.misc import build_from_crawler
from scrapy.utils.spider import DefaultSpider
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
    from scrapy.http import Response

    from tests.mockserver.http import MockServer


curl_cffi = pytest.importorskip("curl_cffi")
Fingerprint = curl_cffi.Fingerprint


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


class TestImpersonation:
    @staticmethod
    async def _download(
        request: Request, settings: dict[str, Any] | None = None
    ) -> Response:
        crawler = get_crawler(DefaultSpider, settings)
        crawler.spider = crawler._create_spider()
        handler = build_from_crawler(CurlCffiDownloadHandler, crawler)
        try:
            return await handler.download_request(request)
        finally:
            await handler.close()

    async def _get_sent_headers(
        self,
        mockserver: MockServer,
        settings: dict[str, Any] | None = None,
        **request_kwargs: Any,
    ) -> Headers:
        request = Request(mockserver.url("/echo", is_secure=True), **request_kwargs)
        response = await self._download(request, settings)
        assert response.protocol == "HTTP/1.1"
        return Headers(json.loads(response.text)["headers"])

    @coroutine_test
    async def test_no_impersonation(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(mockserver)
        assert "User-Agent" not in headers

    @coroutine_test
    async def test_setting(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver, {"CURL_CFFI_IMPERSONATE": "firefox135"}
        )
        assert b"Firefox/135.0" in headers.getlist("User-Agent")[0]

    @coroutine_test
    async def test_setting_alias(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver, {"CURL_CFFI_IMPERSONATE": "chrome"}
        )
        assert b"Chrome/" in headers.getlist("User-Agent")[0]

    @coroutine_test
    async def test_setting_dict(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver,
            {"CURL_CFFI_IMPERSONATE": {"headers": {"User-Agent": "foo", "X-A": "1"}}},
        )
        assert headers.getlist("User-Agent") == [b"foo"]
        assert headers.getlist("X-A") == [b"1"]

    @coroutine_test
    async def test_setting_fingerprint(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver,
            {"CURL_CFFI_IMPERSONATE": Fingerprint(headers={"User-Agent": "foo"})},
        )
        assert headers.getlist("User-Agent") == [b"foo"]

    @coroutine_test
    async def test_meta(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver,
            {"CURL_CFFI_IMPERSONATE": "firefox135"},
            meta={"curl_cffi_impersonate": "chrome136"},
        )
        assert b"Chrome/136" in headers.getlist("User-Agent")[0]

    @coroutine_test
    async def test_request_headers_override(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver,
            {"CURL_CFFI_IMPERSONATE": "firefox135"},
            headers={"User-Agent": "foo"},
        )
        assert headers.getlist("User-Agent") == [b"foo"]
        assert "Sec-Fetch-Mode" in headers

    @coroutine_test
    async def test_no_header_leak(self, mockserver: MockServer) -> None:
        crawler = get_crawler(DefaultSpider)
        crawler.spider = crawler._create_spider()
        handler = build_from_crawler(CurlCffiDownloadHandler, crawler)
        url = mockserver.url("/echo", is_secure=True)
        try:
            for meta in [{"curl_cffi_impersonate": "chrome136"}, {}, {}, {}]:
                response = await handler.download_request(Request(url, meta=meta))
                headers = Headers(json.loads(response.text)["headers"])
                assert ("User-Agent" in headers) == bool(meta)
        finally:
            await handler.close()

    @coroutine_test
    async def test_http2(self, mockserver: MockServer) -> None:
        request = Request(mockserver.url("/text", is_secure=True))
        response = await self._download(
            request,
            {"CURL_CFFI_IMPERSONATE": "chrome136", "CURL_CFFI_HTTP_VERSION": "v2tls"},
        )
        assert response.protocol == "HTTP/2.0"

    @pytest.mark.parametrize(
        "value",
        [
            "chrome0",
            "",
            {"foo": "bar"},
            42,
        ],
    )
    @coroutine_test
    async def test_invalid_setting(self, value: Any) -> None:
        crawler = get_crawler(DefaultSpider, {"CURL_CFFI_IMPERSONATE": value})
        with pytest.raises(NotConfigured, match="Invalid CURL_CFFI_IMPERSONATE value"):
            build_from_crawler(CurlCffiDownloadHandler, crawler)

    @coroutine_test
    async def test_invalid_meta(self, mockserver: MockServer) -> None:
        request = Request(
            mockserver.url("/text", is_secure=True),
            meta={"curl_cffi_impersonate": "chrome0"},
        )
        with pytest.raises(ValueError, match="Unknown impersonation target: 'chrome0'"):
            await self._download(request)


@coroutine_test
async def test_sessions() -> None:
    proxy = "http://proxy.example:8080"
    handler = build_from_crawler(CurlCffiDownloadHandler, get_crawler())
    try:
        default = handler._get_session(None)
        assert handler._get_session(proxy) is default
        assert handler._get_session(None, (("X-A", "1"),)) is default
        assert handler._get_session(None, (), Fingerprint()) is default
        session = handler._get_session(proxy, (("X-A", "1"),))
        assert session is not default
        assert handler._get_session(proxy, (("X-A", "1"),)) is session
        assert (
            handler._get_session("http://other.example:8080", (("X-A", "1"),))
            is session
        )
        assert handler._get_session(proxy, (("X-A", "2"),)) is not session
        impersonate_default = handler._get_session(None, (), "chrome")
        assert impersonate_default is not default
        assert handler._get_session(proxy, (), "firefox") is impersonate_default
        impersonate_session = handler._get_session(proxy, (("X-A", "1"),), "chrome")
        assert impersonate_session not in {default, session, impersonate_default}
        assert len(handler._sessions) == 5
    finally:
        await handler.close()


@coroutine_test
async def test_proxy_headers_ignored_for_socks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    proxy = "socks5://proxy.example:1080"
    handler = build_from_crawler(CurlCffiDownloadHandler, get_crawler())
    try:
        default = handler._get_session(None)
        with caplog.at_level("WARNING"):
            assert handler._get_session(proxy, (("X-A", "1"),)) is default
            assert handler._get_session(proxy, (("X-A", "1"),)) is default
    finally:
        await handler.close()
    assert caplog.text.count("the SOCKS protocol has no headers") == 1
