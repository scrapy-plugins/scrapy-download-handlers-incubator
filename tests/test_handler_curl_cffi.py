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
    TestMitmProxyBase,
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
        from scrapy_download_handlers_incubator import (  # noqa: PLC0415
            CurlCffiDownloadHandler,
        )

        return CurlCffiDownloadHandler


class CurlCffiDownloadHandlerSettingsMixin:
    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_download_handlers_incubator.CurlCffiDownloadHandler",
                "https": "scrapy_download_handlers_incubator.CurlCffiDownloadHandler",
            }
        }


class TestHttp11(CurlCffiDownloadHandlerMixin, TestHttp11Base):
    handler_supports_bindaddress_meta = False


class TestHttps11(CurlCffiDownloadHandlerMixin, TestHttps11Base):
    handler_supports_bindaddress_meta = False

    @pytest.mark.skip(reason="TLS verbose logging is not implemented")
    @coroutine_test
    async def test_tls_logging(self) -> None:  # type: ignore[override]
        pass


class TestHttps2(TestHttps11):
    HTTP2_DATALOSS_SKIP_REASON = "Content-Length mismatch raises InvalidBodyLengthError"

    default_handler_settings: ClassVar[dict[str, Any]] = {
        "CURL_CFFI_HTTP_VERSION": "v2",
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


class TestSimpleHttps(CurlCffiDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttps11WrongHostname(
    CurlCffiDownloadHandlerMixin, TestHttpsWrongHostnameBase
):
    pass


class TestHttps11InvalidDNSId(CurlCffiDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttps11InvalidDNSPattern(
    CurlCffiDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


# custom ciphers are not supported
# class TestHttps11CustomCiphers


class TestHttp11WithCrawler(
    CurlCffiDownloadHandlerSettingsMixin, TestHttpWithCrawlerBase
):
    pass


class TestHttps11WithCrawler(TestHttp11WithCrawler):
    is_secure = True

    @pytest.mark.skip(reason="response.certificate is not implemented")
    @coroutine_test
    async def test_response_ssl_certificate(self, mockserver: MockServer) -> None:
        pass


class TestHttp11Proxy(CurlCffiDownloadHandlerMixin, TestHttpProxyBase):
    expected_http_proxy_request_body = b"http://example.com/"


class TestHttps11Proxy(CurlCffiDownloadHandlerMixin, TestHttpProxyBase):
    is_secure = True
    expected_http_proxy_request_body = TestHttp11Proxy.expected_http_proxy_request_body


class TestMitmProxy(CurlCffiDownloadHandlerSettingsMixin, TestMitmProxyBase):
    pass
