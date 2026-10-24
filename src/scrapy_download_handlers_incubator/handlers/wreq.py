from __future__ import annotations

import ipaddress
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

from scrapy.exceptions import (
    CannotResolveHostError,
    DownloadConnectionRefusedError,
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    UnsupportedURLSchemeError,
)
from scrapy.http import Headers
from scrapy.utils._download_handlers import normalize_bind_address
from scrapy.utils.ssl import _get_keylog_filename, _get_tls_version_limits

from scrapy_download_handlers_incubator.utils import get_proxy_headers

from ._base_streaming import BaseStreamingDownloadHandler, _BaseResponseArgs

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import wreq
    import wreq.exceptions
    import wreq.redirect

    _HTTP_VERSIONS: list[tuple[wreq.Version, str]] = [
        (wreq.Version.HTTP_09, "HTTP/0.9"),
        (wreq.Version.HTTP_10, "HTTP/1.0"),
        (wreq.Version.HTTP_11, "HTTP/1.1"),
        (wreq.Version.HTTP_2, "HTTP/2.0"),
        (wreq.Version.HTTP_3, "HTTP/3.0"),
    ]

    _TLS_VERSION_MAP: dict[str, wreq.TlsVersion] = {
        "TLSv1.0": wreq.TlsVersion.TLS_1_0,
        "TLSv1.1": wreq.TlsVersion.TLS_1_1,
        "TLSv1.2": wreq.TlsVersion.TLS_1_2,
        "TLSv1.3": wreq.TlsVersion.TLS_1_3,
    }
except ImportError:
    wreq = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


if TYPE_CHECKING:
    _Base = BaseStreamingDownloadHandler[wreq.Response]
else:
    _Base = BaseStreamingDownloadHandler


class WreqDownloadHandler(_Base):
    experimental: ClassVar[bool] = True
    supports_per_request_bindaddress: ClassVar[bool] = True

    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        tls_min, tls_max = _get_tls_version_limits(
            crawler.settings, _TLS_VERSION_MAP.__getitem__
        )
        kwargs: dict[str, Any] = {}
        if tls_min is not None:
            kwargs["tls_min_version"] = tls_min
        if tls_max is not None:
            kwargs["tls_max_version"] = tls_max
        if (keylog_filename := _get_keylog_filename()) is not None:
            kwargs["tls_keylog"] = wreq.KeyLog.file(keylog_filename)
        if (bind_host := self._get_bind_address_host()) is not None:
            kwargs["local_address"] = ipaddress.ip_address(bind_host)
        if (emulation := crawler.settings.get("WREQ_EMULATION")) is not None:
            try:
                kwargs["emulation"] = _parse_emulation(emulation)
            except ValueError as e:
                raise NotConfigured(f"Invalid WREQ_EMULATION value: {e}") from e
        self._client = wreq.Client(
            http1_only=not crawler.settings.getbool("WREQ_HTTP2_ENABLED"),
            # number of host buckets in the pool (older extra ones are discarded)
            pool_max_size=self._pool_size_total,
            # number of idle connections per host in the pool (newer extra ones are not put there)
            pool_max_idle_per_host=self._pool_size_per_host,
            tls_verify=crawler.settings.getbool("DOWNLOAD_VERIFY_CERTIFICATES"),
            tls_info=True,
            redirect=wreq.redirect.Policy.none(),
            cookie_store=False,
            referer=False,
            no_proxy=True,
            gzip=False,
            deflate=False,
            brotli=False,
            zstd=False,
            **kwargs,
        )
        self._warned_socks_proxy_headers: bool = False

    @staticmethod
    def _check_deps_installed() -> None:
        if wreq is None:  # pragma: no cover
            raise NotConfigured(
                "WreqDownloadHandler requires the wreq library to be installed."
            )

    def _get_proxy(self, request: Request) -> wreq.Proxy | None:
        proxy_url, proxy_auth = self._extract_proxy(request)
        if proxy_url is None:
            return None
        proxy_headers = get_proxy_headers(request)
        if proxy_url.startswith("socks"):
            if proxy_headers and not self._warned_socks_proxy_headers:
                logger.warning(
                    "Ignoring the proxy_headers request metadata key for SOCKS"
                    " proxies, as the SOCKS protocol has no headers."
                )
                self._warned_socks_proxy_headers = True
            proxy_url = self._extract_proxy_url_with_creds(request)
            assert proxy_url is not None
            return wreq.Proxy.all(proxy_url)
        kwargs: dict[str, Any] = {}
        if proxy_auth is not None:
            kwargs["custom_http_auth"] = proxy_auth
        if proxy_headers:
            headers = wreq.HeaderMap()
            for name, value in proxy_headers:
                if name.lower() == "proxy-authorization":
                    kwargs["custom_http_auth"] = value
                else:
                    headers.append(name, value)
            kwargs["custom_http_headers"] = headers
        return wreq.Proxy.all(proxy_url, **kwargs)

    def _get_request_kwargs(self, request: Request) -> dict[str, Any]:
        headers = wreq.HeaderMap()
        for name, value in self._utf8_request_headers(request):
            headers.append(name, value)
        kwargs: dict[str, Any] = {"headers": headers}
        if request.body:
            kwargs["body"] = request.body
        elif request.method == "POST" and "Content-Length" not in request.headers:
            headers.append("Content-Length", "0")
        if (proxy := self._get_proxy(request)) is not None:
            kwargs["proxy"] = proxy
        if (
            bind_address := normalize_bind_address(request.meta.get("bindaddress"))
        ) is not None:
            kwargs["local_address"] = ipaddress.ip_address(bind_address[0])
        if (emulation := request.meta.get("wreq_emulation")) is not None:
            kwargs["emulation"] = _parse_emulation(emulation)
        return kwargs

    @asynccontextmanager
    async def _make_request(
        self,
        request: Request,
        timeout: float,  # noqa: ASYNC109
    ) -> AsyncIterator[wreq.Response]:
        try:
            method = getattr(wreq.Method, request.method)
        except AttributeError:
            raise DownloadFailedError(
                f"{type(self).__name__} doesn't support the {request.method} method."
            ) from None
        kwargs = self._get_request_kwargs(request)
        try:
            async with self._client.request(
                method,
                request.url,
                timeout=timedelta(seconds=timeout),
                **kwargs,
            ) as response:
                yield response
        except wreq.exceptions.TimeoutError as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except wreq.exceptions.BodyError as e:
            if "TimedOut" in str(e):
                raise DownloadTimeoutError(
                    f"Getting {request.url} took longer than {timeout} seconds."
                ) from e
            raise DownloadFailedError(str(e)) from e
        except wreq.exceptions.BuilderError as e:
            msg = str(e)
            if "BadScheme" in msg:
                raise UnsupportedURLSchemeError(msg) from e
            raise DownloadFailedError(msg) from e
        except wreq.exceptions.ConnectionError as e:
            msg = str(e)
            if "dns error" in msg:
                raise CannotResolveHostError(msg) from e
            raise DownloadConnectionRefusedError(msg) from e
        except wreq.exceptions.ProxyConnectionError as e:
            msg = str(e)
            if "ProxyAuthRequired" in msg:
                msg = f"Proxy Authentication Required (407): {msg}"
            raise DownloadConnectionRefusedError(msg) from e
        except wreq.exceptions.TlsError as e:
            raise DownloadConnectionRefusedError(str(e)) from e
        except (
            wreq.exceptions.RequestError,
            wreq.exceptions.ConnectionResetError,
            wreq.exceptions.DecodingError,
        ) as e:
            raise DownloadFailedError(str(e)) from e

    @staticmethod
    def _extract_headers(response: wreq.Response) -> Headers:
        return Headers(
            [(bytes(name), bytes(value)) for name, value in response.headers]
        )

    @staticmethod
    def _build_base_response_args(
        response: wreq.Response,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        ip_address = None
        if (remote_addr := response.remote_addr) is not None:
            ip_address = remote_addr.ip()
        certificate = None
        if (tls_info := response.tls_info) is not None and (
            cert := tls_info.peer_certificate()
        ) is not None:
            certificate = bytes(cert)
        protocol = None
        for version, name in _HTTP_VERSIONS:
            if response.version == version:
                protocol = name
                break
        return {
            "status": response.status.as_int(),
            "url": request.url,
            "headers": headers,
            "certificate": certificate,
            "ip_address": ip_address,
            "protocol": protocol,
        }

    @staticmethod
    async def _iter_body_chunks(response: wreq.Response) -> AsyncIterator[bytes]:
        async with response.stream() as stream:
            async for chunk in stream:
                # trailers are yielded as HeaderMap objects
                if isinstance(chunk, memoryview):
                    yield chunk.tobytes()

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return isinstance(
            exc,
            (wreq.exceptions.DecodingError, wreq.exceptions.ConnectionResetError),
        )

    async def close(self) -> None:
        self._client.close()


def _parse_emulation(value: str | dict[str, Any]) -> wreq.Emulation | wreq.Profile:
    if isinstance(value, str):
        return _get_enum_member(wreq.Profile, value)
    if isinstance(value, dict):
        kwargs = dict(value)
        if "profile" in kwargs:
            kwargs["profile"] = _get_enum_member(wreq.Profile, kwargs["profile"])
        if "platform" in kwargs:
            kwargs["platform"] = _get_enum_member(wreq.Platform, kwargs["platform"])
        try:
            return wreq.Emulation(**kwargs)
        except TypeError as e:
            raise ValueError(str(e)) from e
    raise ValueError(f"Expected a profile name or a dict, got {value!r}")


def _get_enum_member(enum: type[_T], name: str) -> _T:
    member = getattr(enum, name, None) if isinstance(name, str) else None
    if isinstance(member, enum):
        return member
    raise ValueError(f"Unknown {enum.__name__} value: {name!r}")
