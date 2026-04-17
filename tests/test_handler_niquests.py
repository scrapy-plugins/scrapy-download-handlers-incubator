from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

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
    handler_supports_bindaddress_meta = False
    handler_merges_headers = True
    # urllib3.future always adds these, even with an empty session.headers
    always_present_req_headers = frozenset({"Accept-Encoding", "User-Agent"})

    @coroutine_test
    async def test_unsupported_proxy(self, mockserver: MockServer) -> None:
        meta = {"proxy": "127.0.0.2"}
        request = Request(mockserver.url("/text"), meta=meta)
        async with self.get_dh() as download_handler:
            with pytest.raises(NotImplementedError, match="doesn't support proxies"):
                await download_handler.download_request(request)


class TestHttps11(NiquestsDownloadHandlerMixin, TestHttps11Base):
    handler_supports_bindaddress_meta = False
    handler_merges_headers = True
    always_present_req_headers = TestHttp11.always_present_req_headers
    tls_log_message = "SSL connection to 127.0.0.1 using protocol TLSv1_3, cipher"


class TestHttps2(TestHttps11):
    HTTP2_DATALOSS_SKIP_REASON = "Content-Length mismatch raises InvalidBodyLengthError"

    default_handler_settings: ClassVar[dict[str, Any]] = {
        "NIQUESTS_HTTP2_ENABLED": True,
    }

    @coroutine_test
    async def test_protocol(self, mockserver: MockServer) -> None:
        request = Request(mockserver.url("/host", is_secure=self.is_secure))
        async with self.get_dh() as download_handler:
            response = await download_handler.download_request(request)
        assert response.protocol == "HTTP/2.0"

    def test_download_cause_data_loss(self) -> None:  # type: ignore[override]
        pytest.skip(self.HTTP2_DATALOSS_SKIP_REASON)

    def test_download_cause_data_loss_double_warning(self) -> None:  # type: ignore[override]
        pytest.skip(self.HTTP2_DATALOSS_SKIP_REASON)

    def test_download_allow_data_loss(self) -> None:  # type: ignore[override]
        pytest.skip(self.HTTP2_DATALOSS_SKIP_REASON)

    def test_download_allow_data_loss_via_setting(self) -> None:  # type: ignore[override]
        pytest.skip(self.HTTP2_DATALOSS_SKIP_REASON)

    def test_download_conn_aborted(self) -> None:  # type: ignore[override]
        pytest.skip(self.HTTP2_DATALOSS_SKIP_REASON)


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
