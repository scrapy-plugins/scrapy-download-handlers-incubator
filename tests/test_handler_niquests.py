from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from scrapy import Request
from scrapy.utils.misc import build_from_crawler
from scrapy.utils.test import get_crawler

from scrapy_download_handlers_incubator import NiquestsDownloadHandler
from scrapy_download_handlers_incubator.handlers.niquests import (  # type: ignore[attr-defined]
    niquests,
)
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


pytest.importorskip("niquests")


class NiquestsDownloadHandlerMixin:
    @property
    def download_handler_cls(self) -> type[DownloadHandlerProtocol]:
        return NiquestsDownloadHandler

    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_download_handlers_incubator.NiquestsDownloadHandler",
                "https": "scrapy_download_handlers_incubator.NiquestsDownloadHandler",
            }
        }


class TestHttp(NiquestsDownloadHandlerMixin, TestHttpBase):
    handler_supports_bindaddress_meta = False
    # niquests.structures.CaseInsensitiveDict doesn't support multiple values
    handler_merges_request_headers = True
    # urllib3.future percent-encodes RFC 3986-invalid characters, e.g. [ into %5B
    handler_supports_verbatim_urls = False
    handler_bad_header_handling = "fail"
    # urllib3.future always adds these, even with an empty session.headers
    always_present_req_headers = frozenset({"Accept-Encoding", "User-Agent"})


class TestHttps(NiquestsDownloadHandlerMixin, TestHttpsBase):
    handler_supports_bindaddress_meta = False
    handler_merges_request_headers = True
    handler_supports_verbatim_urls = False
    handler_bad_header_handling = "fail"
    handler_supports_keylogging = False
    always_present_req_headers = TestHttp.always_present_req_headers
    tls_log_message = "SSL connection to 127.0.0.1 using protocol TLSv1_3, cipher"


class TestHttp2(TestHttps):
    http2 = True

    default_handler_settings: ClassVar[dict[str, Any]] = {
        "NIQUESTS_HTTP2_ENABLED": True,
    }

    @coroutine_test
    async def test_protocol(self, mockserver: MockServer) -> None:
        request = Request(mockserver.url("/host", is_secure=self.is_secure))
        async with self.get_dh() as download_handler:
            response = await download_handler.download_request(request)
        assert response.protocol == "HTTP/2.0"

    @pytest.mark.skip(
        reason="InvalidBodyLengthError can be raised before reading the body"
    )
    def test_download_cause_data_loss(self) -> None:  # type: ignore[override]
        pass

    @pytest.mark.skip(
        reason="InvalidBodyLengthError can be raised before reading the body"
    )
    def test_download_cause_data_loss_double_warning(self) -> None:  # type: ignore[override]
        pass

    @pytest.mark.skip(
        reason="InvalidBodyLengthError can be raised before reading the body"
    )
    def test_download_allow_data_loss_broken(self) -> None:  # type: ignore[override]
        pass

    @pytest.mark.skip(
        reason="InvalidBodyLengthError can be raised before reading the body"
    )
    def test_download_allow_data_loss_via_setting(self) -> None:  # type: ignore[override]
        pass


class TestSimpleHttps(NiquestsDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttpsWrongHostname(NiquestsDownloadHandlerMixin, TestHttpsWrongHostnameBase):
    pass


class TestHttpsInvalidDNSId(NiquestsDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttpsInvalidDNSPattern(
    NiquestsDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


# custom ciphers are not supported
# class TestHttpsCustomCiphers
# class TestHttpsDefaultCiphers


class TestHttpsTLSVersion(NiquestsDownloadHandlerMixin, TestHttpsTLSVersionBase):
    pass


class TestHttpWithCrawler(NiquestsDownloadHandlerMixin, TestHttpWithCrawlerBase):
    pass


class TestHttpsWithCrawler(TestHttpWithCrawler):
    is_secure = True


class TestHttpProxy(NiquestsDownloadHandlerMixin, TestHttpProxyBase):
    @pytest.mark.skip(reason="Hangs, as the test is hacky")
    def test_download_with_proxy_https_timeout(self) -> None:  # type: ignore[override]
        pass


class TestHttpsProxy(NiquestsDownloadHandlerMixin, TestHttpProxyBase):
    is_secure = True

    @pytest.mark.skip(reason="Hangs, as the test is hacky")
    def test_download_with_proxy_https_timeout(self) -> None:  # type: ignore[override]
        pass


class TestMitmProxy(NiquestsDownloadHandlerMixin, TestMitmProxyBase):
    pass


@pytest.mark.requires_internet
class TestRealWebsite(NiquestsDownloadHandlerMixin, TestRealWebsiteBase):
    pass


@coroutine_test
async def test_proxy_header_sessions() -> None:
    proxy = "http://proxy.example:8080"
    handler = build_from_crawler(NiquestsDownloadHandler, get_crawler())
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
    handler = build_from_crawler(NiquestsDownloadHandler, get_crawler())
    try:
        with caplog.at_level("WARNING"):
            assert handler._get_session(proxy, (("X-A", "1"),)) is handler._session
            assert handler._get_session(proxy, (("X-A", "1"),)) is handler._session
    finally:
        await handler.close()
    assert caplog.text.count("the SOCKS protocol has no headers") == 1


@coroutine_test
async def test_proxy_headers_replace_proxy_authorization() -> None:
    handler = build_from_crawler(NiquestsDownloadHandler, get_crawler())
    try:
        session = handler._get_session(
            "http://proxy.example:8080", (("proxy-authorization", "Custom x"),)
        )
        adapter = session.get_adapter("http://example.com")
        assert isinstance(adapter, niquests.adapters.AsyncHTTPAdapter)
        assert adapter.proxy_headers("http://user:pass@proxy.example:8080") == {
            "proxy-authorization": "Custom x"
        }
    finally:
        await handler.close()
