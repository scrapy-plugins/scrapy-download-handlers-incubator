from __future__ import annotations

import json
import sys
from functools import partial
from ipaddress import IPv4Address
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from scrapy import Request
from scrapy.exceptions import DownloadFailedError, NotConfigured
from scrapy.http import Headers
from scrapy.utils.misc import build_from_crawler
from scrapy.utils.spider import DefaultSpider
from scrapy.utils.test import get_crawler

from scrapy_download_handlers_incubator import WreqDownloadHandler
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
from tests.utils import IDNA_REJECTED_HOSTNAMES
from tests.utils.decorators import coroutine_test

if TYPE_CHECKING:
    from scrapy.core.downloader.handlers import DownloadHandlerProtocol
    from scrapy.http import Response

    from tests.mockserver.http import MockServer


wreq = pytest.importorskip("wreq")


class WreqDownloadHandlerMixin:
    @property
    def download_handler_cls(self) -> type[DownloadHandlerProtocol]:
        return WreqDownloadHandler

    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_download_handlers_incubator.WreqDownloadHandler",
                "https": "scrapy_download_handlers_incubator.WreqDownloadHandler",
            }
        }


class TestHttp(WreqDownloadHandlerMixin, TestHttpBase):
    handler_bad_header_handling = "fail"
    handler_non_utf8_request_header_handling = "replace"

    @pytest.fixture
    def resolve_to_loopback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # wreq resolves hostnames in Rust
        dns_options = wreq.DnsOptions()
        for hostname in IDNA_REJECTED_HOSTNAMES:
            dns_options.add_resolve(hostname, [IPv4Address("127.0.0.1")])
        monkeypatch.setattr(
            wreq, "Client", partial(wreq.Client, dns_options=dns_options)
        )

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
    async def test_unsupported_method(self, mockserver: MockServer) -> None:
        request = Request(mockserver.url("/text"), method="PROPFIND")
        async with self.get_dh() as download_handler:
            with pytest.raises(
                DownloadFailedError, match="doesn't support the PROPFIND method"
            ):
                await download_handler.download_request(request)


class TestHttps(WreqDownloadHandlerMixin, TestHttpsBase):
    handler_bad_header_handling = "fail"
    handler_non_utf8_request_header_handling = "replace"
    handler_supports_tls_logging = False

    resolve_to_loopback = TestHttp.resolve_to_loopback


class TestHttp2(TestHttps):
    http2 = True

    default_handler_settings: ClassVar[dict[str, Any]] = {
        "WREQ_HTTP2_ENABLED": True,
    }

    @coroutine_test
    async def test_protocol(self, mockserver: MockServer) -> None:
        request = Request(mockserver.url("/host", is_secure=self.is_secure))
        async with self.get_dh() as download_handler:
            response = await download_handler.download_request(request)
        assert response.protocol == "HTTP/2.0"


class TestSimpleHttps(WreqDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttpsWrongHostname(WreqDownloadHandlerMixin, TestHttpsWrongHostnameBase):
    pass


class TestHttpsInvalidDNSId(WreqDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttpsInvalidDNSPattern(
    WreqDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


# custom ciphers are not supported
# class TestHttpsCustomCiphers
# class TestHttpsDefaultCiphers


class TestHttpsTLSVersion(WreqDownloadHandlerMixin, TestHttpsTLSVersionBase):
    pass


class TestHttpWithCrawler(WreqDownloadHandlerMixin, TestHttpWithCrawlerBase):
    pass


class TestHttpsWithCrawler(TestHttpWithCrawler):
    is_secure = True


class TestHttpProxy(WreqDownloadHandlerMixin, TestHttpProxyBase):
    expected_http_proxy_request_body = b"http://example.com/"


class TestHttpsProxy(TestHttpProxy):
    is_secure = True


class TestMitmProxy(WreqDownloadHandlerMixin, TestMitmProxyBase):
    handler_supports_socks = True


@pytest.mark.requires_internet
class TestRealWebsite(WreqDownloadHandlerMixin, TestRealWebsiteBase):
    handler_supports_tls_logging = False


class TestEmulation:
    @staticmethod
    async def _download(
        request: Request, settings: dict[str, Any] | None = None
    ) -> Response:
        crawler = get_crawler(DefaultSpider, settings)
        crawler.spider = crawler._create_spider()
        handler = build_from_crawler(WreqDownloadHandler, crawler)
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
    async def test_no_emulation(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(mockserver)
        assert "User-Agent" not in headers

    @coroutine_test
    async def test_setting(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver, {"WREQ_EMULATION": "Firefox136"}
        )
        assert b"Firefox/136.0" in headers.getlist("User-Agent")[0]

    @coroutine_test
    async def test_setting_dict(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver,
            {"WREQ_EMULATION": {"profile": "Chrome149", "platform": "Windows"}},
        )
        assert b"Chrome/149" in headers.getlist("User-Agent")[0]
        assert headers.getlist("Sec-Ch-Ua-Platform") == [b'"Windows"']

    @coroutine_test
    async def test_meta(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver,
            {"WREQ_EMULATION": "Firefox136"},
            meta={"wreq_emulation": {"profile": "Chrome149"}},
        )
        assert b"Chrome/149" in headers.getlist("User-Agent")[0]

    @coroutine_test
    async def test_request_headers_override(self, mockserver: MockServer) -> None:
        headers = await self._get_sent_headers(
            mockserver,
            {"WREQ_EMULATION": "Firefox136"},
            headers={"User-Agent": "foo"},
        )
        assert headers.getlist("User-Agent") == [b"foo"]
        assert "Sec-Fetch-Mode" in headers

    @coroutine_test
    async def test_http2(self, mockserver: MockServer) -> None:
        request = Request(mockserver.url("/text", is_secure=True))
        response = await self._download(
            request, {"WREQ_EMULATION": "Chrome149", "WREQ_HTTP2_ENABLED": True}
        )
        assert response.protocol == "HTTP/2.0"

    @pytest.mark.parametrize(
        "value",
        [
            "Firefox0",
            "random",
            {"profile": "Firefox0"},
            {"platform": "Amiga"},
            {"foo": "bar"},
            42,
        ],
    )
    @coroutine_test
    async def test_invalid_setting(self, value: Any) -> None:
        crawler = get_crawler(DefaultSpider, {"WREQ_EMULATION": value})
        with pytest.raises(NotConfigured, match="Invalid WREQ_EMULATION value"):
            build_from_crawler(WreqDownloadHandler, crawler)

    @coroutine_test
    async def test_invalid_meta(self, mockserver: MockServer) -> None:
        request = Request(
            mockserver.url("/text", is_secure=True),
            meta={"wreq_emulation": "Firefox0"},
        )
        with pytest.raises(ValueError, match="Unknown Profile value: 'Firefox0'"):
            await self._download(request)


@coroutine_test
async def test_proxy_auth_and_headers() -> None:
    handler = build_from_crawler(WreqDownloadHandler, get_crawler())
    try:
        proxy = handler._get_proxy(
            Request(
                "https://example.com",
                headers={"Proxy-Authorization": "Basic dXNlcjpwYXNz"},
                meta={"proxy": "http://proxy.example:8080"},
            )
        )
        assert 'auth: Some("Basic dXNlcjpwYXNz")' in str(proxy)
        proxy = handler._get_proxy(
            Request(
                "https://example.com",
                headers={"Proxy-Authorization": "Basic dXNlcjpwYXNz"},
                meta={
                    "proxy": "http://proxy.example:8080",
                    "proxy_headers": {"X-A": "1", "Proxy-Authorization": "Custom x"},
                },
            )
        )
        assert 'auth: Some("Custom x")' in str(proxy)
        assert '"x-a": "1"' in str(proxy)
        assert handler._get_proxy(Request("https://example.com")) is None
    finally:
        await handler.close()


@coroutine_test
async def test_socks_proxy(caplog: pytest.LogCaptureFixture) -> None:
    handler = build_from_crawler(WreqDownloadHandler, get_crawler())
    request = Request(
        "https://example.com",
        headers={"Proxy-Authorization": "Basic dXNlcjpwYXNz"},
        meta={"proxy": "socks5://proxy.example:1080", "proxy_headers": {"X-A": "1"}},
    )
    try:
        with caplog.at_level("WARNING"):
            proxy = handler._get_proxy(request)
            handler._get_proxy(request)
    finally:
        await handler.close()
    assert "socks5://user:pass@proxy.example:1080" in str(proxy)
    assert caplog.text.count("the SOCKS protocol has no headers") == 1
