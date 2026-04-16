"""``curl_cffi``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

from scrapy.exceptions import (
    CannotResolveHostError,
    DownloadConnectionRefusedError,
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    UnsupportedURLSchemeError,
)
from scrapy.http import Headers

from scrapy_download_handlers_incubator.handlers._base import (
    BaseIncubatorDownloadHandler,
    _BaseResponseArgs,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import curl_cffi.requests.session
    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import curl_cffi.const
    import curl_cffi.requests.exceptions

    _HTTP_VERSION_MAP: dict[int, str] = {
        curl_cffi.const.CurlHttpVersion.V1_0: "HTTP/1.0",
        curl_cffi.const.CurlHttpVersion.V1_1: "HTTP/1.1",
        curl_cffi.const.CurlHttpVersion.V2_0: "HTTP/2.0",
        curl_cffi.const.CurlHttpVersion.V3: "HTTP/3",
    }
except ImportError:
    curl_cffi = None  # type: ignore[assignment]


if TYPE_CHECKING:
    _Base = BaseIncubatorDownloadHandler[curl_cffi.Response]
else:
    _Base = BaseIncubatorDownloadHandler


class CurlCffiDownloadHandler(_Base):
    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        # _ssl_context = _make_ssl_context(crawler.settings)
        verify_certificates: bool = crawler.settings.getbool(
            "DOWNLOAD_VERIFY_CERTIFICATES"
        )
        if crawler.settings.getbool("CURL_CFFI_HTTP2_ENABLED"):
            http_version = curl_cffi.const.CurlHttpVersion.V2TLS
        else:
            http_version = curl_cffi.const.CurlHttpVersion.V1_1
        self._session: curl_cffi.AsyncSession[curl_cffi.Response] = (
            curl_cffi.AsyncSession(
                interface=self._get_bind_address_host(),
                allow_redirects=False,
                discard_cookies=True,
                trust_env=False,
                verify=verify_certificates,
                default_headers=False,
                # hard limit on simultaneous connections
                max_clients=self._pool_size_total,
                http_version=http_version,
            )
        )

    @staticmethod
    def _check_deps_installed() -> None:
        if curl_cffi is None:  # pragma: no cover
            raise NotConfigured(
                "CurlCffiDownloadHandler requires the curl_cffi library to be installed."
            )

    @asynccontextmanager
    async def _make_request(  # noqa: PLR0912
        self, request: Request, timeout: float
    ) -> AsyncIterator[curl_cffi.Response]:
        response: curl_cffi.Response | None = None
        try:
            response = await self._session.request(
                cast("curl_cffi.requests.session.HttpMethod", request.method),
                request.url,
                data=request.body,
                headers=request.headers.to_tuple_list(),
                # not exactly followed because of how it's implemented in libcurl
                timeout=timeout,
                accept_encoding=None,
                stream=True,
            )
            yield response
        except curl_cffi.requests.exceptions.RequestException as e:
            # In the streaming mode the wrapper exception is always RequestException:
            # https://github.com/lexiforest/curl_cffi/issues/744
            # So we do mapping ourselves.
            mapped_e_cls = curl_cffi.requests.exceptions.code2error(
                cast("curl_cffi.CurlECode", e.code), str(e)
            )
            match mapped_e_cls:
                case curl_cffi.requests.exceptions.Timeout:
                    raise DownloadTimeoutError(
                        f"Getting {request.url} took longer than {timeout} seconds."
                    ) from e
                case curl_cffi.requests.exceptions.InvalidSchema:
                    raise UnsupportedURLSchemeError(str(e)) from e
                case curl_cffi.requests.exceptions.DNSError:
                    raise CannotResolveHostError(str(e)) from e
                case curl_cffi.requests.exceptions.ConnectionError:
                    if e.code in {
                        curl_cffi.const.CurlECode.SEND_ERROR,
                        curl_cffi.const.CurlECode.RECV_ERROR,
                    }:
                        raise DownloadFailedError(str(e)) from e
                    raise DownloadConnectionRefusedError(str(e)) from e
                case curl_cffi.requests.exceptions.CertificateVerifyError:
                    raise DownloadConnectionRefusedError(str(e)) from e
                case curl_cffi.requests.exceptions.RequestException:
                    raise DownloadFailedError(str(e)) from e
                case _:
                    raise
        finally:
            if response is not None:
                # work around hanging in e.g. test_download_with_content_length()
                task = response.astream_task
                if (
                    task is not None
                    and isinstance(task, asyncio.Task)
                    and not task.done()
                ):
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                else:
                    await response.aclose()  # type: ignore[no-untyped-call]

    @staticmethod
    def _extract_headers(response: curl_cffi.Response) -> Headers:
        return Headers(response.headers.multi_items())

    @staticmethod
    def _build_base_response_args(
        response: curl_cffi.Response,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        ip_address = None
        if response.primary_ip:
            ip_address = ipaddress.ip_address(response.primary_ip)
        return {
            "status": response.status_code,
            "url": request.url,
            "headers": headers,
            "ip_address": ip_address,
            "protocol": _HTTP_VERSION_MAP.get(response.http_version, ""),
        }

    @staticmethod
    async def _iter_body_chunks(response: curl_cffi.Response) -> AsyncIterator[bytes]:
        async for chunk in response.aiter_content():  # type: ignore[no-untyped-call]
            yield chunk

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        # mapped to curl_cffi.requests.exceptions.IncompleteRead
        return (
            isinstance(exc, curl_cffi.requests.exceptions.RequestException)
            and exc.code == curl_cffi.const.CurlECode.PARTIAL_FILE
        )

    async def close(self) -> None:
        await self._session.close()
