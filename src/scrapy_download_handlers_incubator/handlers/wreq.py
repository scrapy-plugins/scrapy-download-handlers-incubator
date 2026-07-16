"""``wreq``-based HTTP(S) download handler. Currently not recommended for production use."""

from __future__ import annotations

import base64
import ipaddress
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import TYPE_CHECKING, ClassVar

from scrapy.core.downloader.handlers._base_streaming import (
    BaseStreamingDownloadHandler,
    _BaseResponseArgs,
)
from scrapy.exceptions import (
    CannotResolveHostError,
    DownloadConnectionRefusedError,
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    UnsupportedURLSchemeError,
)
from scrapy.http import Headers

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import wreq
except ImportError:
    wreq = None  # type: ignore[assignment]


if TYPE_CHECKING:
    _Base = BaseStreamingDownloadHandler[wreq.Response]
else:
    _Base = BaseStreamingDownloadHandler


class WreqDownloadHandler(_Base):
    experimental: ClassVar[bool] = True

    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        verify_certificates: bool = crawler.settings.getbool(
            "DOWNLOAD_VERIFY_CERTIFICATES"
        )
        self._enable_h2: bool = crawler.settings.getbool("WREQ_HTTP2_ENABLED")
        kwargs = {}
        if (bind_host := self._get_bind_address_host()) is not None:
            kwargs["local_address"] = ipaddress.ip_address(bind_host)
        self._client = wreq.Client(
            http1_only=not self._enable_h2,
            pool_max_size=self._pool_size_total,
            pool_max_idle_per_host=self._pool_size_per_host,
            tls_verify=verify_certificates,
            gzip=False,
            deflate=False,
            brotli=False,
            zstd=False,
            **kwargs,
        )

    @staticmethod
    def _check_deps_installed() -> None:
        if wreq is None:  # pragma: no cover
            raise NotConfigured(
                "WreqDownloadHandler requires the wreq library to be installed."
            )

    @asynccontextmanager
    async def _make_request(
        self, request: Request, timeout: float
    ) -> AsyncIterator[wreq.Response]:
        proxy_url, proxy_auth = self._extract_proxy(request)
        if proxy_url is not None:
            proxy_user, proxy_pass = (
                self._decode_proxy_auth(proxy_auth) if proxy_auth else (None, None)
            )
            proxy = wreq.Proxy.all(proxy_url, username=proxy_user, password=proxy_pass)
        else:
            proxy = None
        headers = wreq.HeaderMap()
        for key, value in request.headers.to_tuple_list():
            headers.append(key, value)
        try:
            async with await self._client.request(
                getattr(wreq.Method, request.method),
                request.url,
                body=request.body,
                headers=headers,
                timeout=timedelta(seconds=timeout),
                proxy=proxy,
            ) as response:
                yield response
        except wreq.exceptions.TimeoutError as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except wreq.exceptions.BuilderError as e:
            msg = str(e)
            if "BadScheme" in msg:
                raise UnsupportedURLSchemeError(msg) from e
            raise DownloadFailedError(msg) from e
        except wreq.exceptions.ConnectionError as e:
            msg = str(e)
            if "ResolveError" in msg:
                raise CannotResolveHostError(msg) from e
            raise DownloadConnectionRefusedError(msg) from e
        except (wreq.exceptions.TlsError, wreq.exceptions.ProxyConnectionError) as e:
            raise DownloadConnectionRefusedError(str(e)) from e
        except wreq.exceptions.RequestError as e:
            raise DownloadFailedError(str(e)) from e

    @staticmethod
    def _extract_headers(response: wreq.Response) -> Headers:
        return Headers(response.headers)

    @staticmethod
    def _build_base_response_args(
        response: wreq.Response,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
        if (remote := response.remote_addr) is not None:
            ip_address = remote.ip()

        if (tls_info := response.tls_info) is not None:
            cert = tls_info.peer_certificate()
        else:
            cert = None

        # _VERSION_TO_STRING: dict[wreq.Version, str] = {
        #     wreq.Version.HTTP_09: "HTTP/0.9",
        #     wreq.Version.HTTP_10: "HTTP/1.0",
        #     wreq.Version.HTTP_11: "HTTP/1.1",
        #     wreq.Version.HTTP_2: "HTTP/2.0",
        #     wreq.Version.HTTP_3: "HTTP/3.0",
        # }
        return {
            "status": response.status.as_int(),
            "url": request.url,
            "headers": headers,
            "certificate": cert,
            "ip_address": ip_address,
            # "protocol": _VERSION_TO_STRING.get(response.version),
            "protocol": None,
        }

    @staticmethod
    async def _iter_body_chunks(response: wreq.Response) -> AsyncIterator[bytes]:
        async with response.stream() as stream:
            async for chunk in stream:
                yield chunk

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return isinstance(
            exc,
            (wreq.exceptions.DecodingError,),
        )

    async def close(self) -> None:
        self._client.close()

    def _decode_proxy_auth(self, header: str) -> tuple[str, str]:
        scheme, token = header.split(" ", 1)
        if scheme != "Basic":
            raise ValueError(
                f"Expected Basic auth in Proxy-Authorization, got {scheme}"
            )
        return tuple(
            base64.b64decode(token).decode(self._proxy_auth_encoding).split(":", 1)
        )
