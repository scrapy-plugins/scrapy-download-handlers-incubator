"""``pyreqwest``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar

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
    BaseStreamingDownloadHandler,
    _BaseResponseArgs,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import pyreqwest.bytes
    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import pyreqwest.client
    import pyreqwest.exceptions
    import pyreqwest.request
    import pyreqwest.response
except ImportError:
    pyreqwest = None  # type: ignore[assignment]


if TYPE_CHECKING:
    _Base = BaseStreamingDownloadHandler[pyreqwest.response.Response]
else:
    _Base = BaseStreamingDownloadHandler


class PyreqwestDownloadHandler(_Base):
    # reqwest doesn't support per-request proxies, see e.g.
    # https://github.com/seanmonstar/reqwest/issues/1764, while Scrapy doesn't
    # support global proxies (HttpProxyMiddleware converts them to request meta)
    supports_proxies: ClassVar[bool] = False

    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        enable_h2 = crawler.settings.getbool("PYREQWEST_HTTP2_ENABLED")
        builder: pyreqwest.client.ClientBuilder = (
            pyreqwest.client.ClientBuilder()
            .http2(enable_h2)
            .follow_redirects(False)
            .default_cookie_store(False)
            .no_proxy()
            # hard limit on simultaneous connections
            .max_connections(self._pool_size_total)
            # number of idle connections per host in the pool (newer extra ones are not put there)
            .pool_max_idle_per_host(self._pool_size_per_host)
            .gzip(False)
            .deflate(False)
            .brotli(False)
            .zstd(False)
        )

        if not crawler.settings.getbool("DOWNLOAD_VERIFY_CERTIFICATES"):
            builder = builder.danger_accept_invalid_certs(True)

        if (host := self._get_bind_address_host()) is not None:
            builder = builder.local_address(host)

        self._client: pyreqwest.client.Client = builder.build()

    @staticmethod
    def _check_deps_installed() -> None:
        if pyreqwest is None:  # pragma: no cover
            raise NotConfigured(
                "PyreqwestDownloadHandler requires the pyreqwest library to be installed."
            )

    @asynccontextmanager
    async def _make_request(
        self, request: Request, timeout: float
    ) -> AsyncIterator[pyreqwest.response.Response]:
        rb: pyreqwest.request.RequestBuilder = (
            self._client.request(request.method, request.url)
            .timeout(timedelta(seconds=timeout))
            # don't start reading the body early, which breaks the logic flow
            .streamed_read_buffer_limit(0)
        )
        headers = request.headers.to_tuple_list()
        if request.body:
            rb = rb.body_bytes(request.body)
        elif request.method == "POST" and "Content-Length" not in request.headers:
            headers.append(("Content-Length", "0"))
        rb = rb.headers(headers)
        try:
            async with rb.build_streamed() as response:
                yield response
        except (
            pyreqwest.exceptions.ConnectTimeoutError,
            pyreqwest.exceptions.ReadTimeoutError,
        ) as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except pyreqwest.exceptions.BuilderError as e:
            if _find_in_causes(e, "URL scheme is not allowed"):
                raise UnsupportedURLSchemeError(str(e)) from e
            raise
        except pyreqwest.exceptions.ConnectError as e:
            if _find_in_causes(e, "dns error"):
                raise CannotResolveHostError(str(e)) from e
            if _find_in_causes(e, "tcp connect error"):
                raise DownloadConnectionRefusedError(str(e)) from e
            raise DownloadFailedError(str(e)) from e

    @staticmethod
    def _extract_headers(response: pyreqwest.response.Response) -> Headers:
        return Headers(list(response.headers.items()))

    @staticmethod
    def _build_base_response_args(
        response: pyreqwest.response.Response,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        return {
            "status": response.status,
            "url": request.url,
            "headers": headers,
            "protocol": response.version,
        }

    @staticmethod
    async def _iter_body_chunks(
        response: pyreqwest.response.Response,
    ) -> AsyncIterator[pyreqwest.bytes.Bytes]:
        while (chunk := await response.body_reader.read_chunk()) is not None:
            yield chunk

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return isinstance(exc, pyreqwest.exceptions.RequestError) and _find_in_causes(
            exc, "error reading a body from connection"
        )

    async def close(self) -> None:
        await self._client.close()


def _find_in_causes(
    ex: pyreqwest.exceptions.DetailedPyreqwestError, substring: str
) -> bool:
    return any(substring in cause["message"] for cause in ex.details["causes"] or [])
