from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
from scrapy import Request

from tests.test_handlers_base import (
    TestHttp11Base,
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


pytest.importorskip("pyreqwest")


class PyreqwestDownloadHandlerMixin:
    @property
    def download_handler_cls(self) -> type[DownloadHandlerProtocol]:
        from scrapy_download_handlers_incubator import (  # noqa: PLC0415
            PyreqwestDownloadHandler,
        )

        return PyreqwestDownloadHandler


class PyreqwestDownloadHandlerSettingsMixin:
    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_download_handlers_incubator.PyreqwestDownloadHandler",
                "https": "scrapy_download_handlers_incubator.PyreqwestDownloadHandler",
            }
        }


class TestHttp11(PyreqwestDownloadHandlerMixin, TestHttp11Base):
    handler_supports_bindaddress_meta = False
    always_present_req_headers = frozenset({"Accept", "User-Agent"})

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
    async def test_unsupported_proxy(self, mockserver: MockServer) -> None:
        meta = {"proxy": "127.0.0.2"}
        request = Request(mockserver.url("/text"), meta=meta)
        async with self.get_dh() as download_handler:
            with pytest.raises(NotImplementedError, match="doesn't support proxies"):
                await download_handler.download_request(request)


class TestHttps11(PyreqwestDownloadHandlerMixin, TestHttps11Base):
    handler_supports_bindaddress_meta = False
    always_present_req_headers = TestHttp11.always_present_req_headers

    @pytest.mark.skip(reason="TLS verbose logging is not implemented")
    @coroutine_test
    async def test_tls_logging(self) -> None:  # type: ignore[override]
        pass


class TestHttps2(TestHttps11):
    HTTP2_DATALOSS_SKIP_REASON = "Content-Length mismatch raises InvalidBodyLengthError"

    default_handler_settings: ClassVar[dict[str, Any]] = {
        "PYREQWEST_HTTP2_ENABLED": True,
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


class TestSimpleHttps(PyreqwestDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttps11WrongHostname(
    PyreqwestDownloadHandlerMixin, TestHttpsWrongHostnameBase
):
    pass


class TestHttps11InvalidDNSId(PyreqwestDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttps11InvalidDNSPattern(
    PyreqwestDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


# custom ciphers are not supported
# class TestHttps11CustomCiphers


class TestHttp11WithCrawler(
    PyreqwestDownloadHandlerSettingsMixin, TestHttpWithCrawlerBase
):
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


# Proxies aren't supported
# class TestHttp11Proxy
# class TestHttps11Proxy
# class TestMitmProxy
