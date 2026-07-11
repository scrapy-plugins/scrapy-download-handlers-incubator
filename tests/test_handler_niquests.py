from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from scrapy import Request

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
        from scrapy_download_handlers_incubator import (  # noqa: PLC0415
            NiquestsDownloadHandler,
        )

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
    # urllib3.future always adds these, even with an empty session.headers
    always_present_req_headers = frozenset({"Accept-Encoding", "User-Agent"})


class TestHttps(NiquestsDownloadHandlerMixin, TestHttpsBase):
    handler_supports_bindaddress_meta = False
    handler_merges_request_headers = True
    handler_supports_verbatim_urls = False
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
