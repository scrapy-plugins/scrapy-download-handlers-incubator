from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, ClassVar, cast

from scrapy.exceptions import (
    CannotResolveHostError,
    DownloadConnectionRefusedError,
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    UnsupportedURLSchemeError,
)
from scrapy.http import Headers
from scrapy.utils.ssl import _get_tls_version_limits

from scrapy_download_handlers_incubator.utils import get_proxy_headers

from ._base_streaming import BaseStreamingDownloadHandler, _BaseResponseArgs

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import curl_cffi.requests.session
    import curl_cffi.requests.utils
    from scrapy import Request
    from scrapy.crawler import Crawler


try:
    import curl_cffi.requests.exceptions
    import curl_cffi.requests.impersonate

    _HTTP_VERSION_MAP: dict[int, str] = {
        curl_cffi.CurlHttpVersion.V1_0: "HTTP/1.0",
        curl_cffi.CurlHttpVersion.V1_1: "HTTP/1.1",
        curl_cffi.CurlHttpVersion.V2_0: "HTTP/2.0",
        curl_cffi.CurlHttpVersion.V3: "HTTP/3",
    }

    _TLS_VERSION_MAP: dict[str, int] = {
        "TLSv1.0": curl_cffi.CurlSslVersion.TLSv1_0,
        "TLSv1.1": curl_cffi.CurlSslVersion.TLSv1_1,
        "TLSv1.2": curl_cffi.CurlSslVersion.TLSv1_2,
        "TLSv1.3": curl_cffi.CurlSslVersion.TLSv1_3,
    }
except ImportError:
    curl_cffi = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    _Base = BaseStreamingDownloadHandler[curl_cffi.Response]
else:
    _Base = BaseStreamingDownloadHandler


class CurlCffiDownloadHandler(_Base):
    experimental: ClassVar[bool] = True

    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        verify_certificates: bool = crawler.settings.getbool(
            "DOWNLOAD_VERIFY_CERTIFICATES"
        )
        curl_options: dict[curl_cffi.CurlOpt, object] = {}
        if not verify_certificates:
            # disable proxy cert verification for test simplification and to match other handlers
            curl_options[curl_cffi.CurlOpt.PROXY_SSL_VERIFYPEER] = 0
            curl_options[curl_cffi.CurlOpt.PROXY_SSL_VERIFYHOST] = 0
        tls_min, tls_max = _get_tls_version_limits(
            crawler.settings, _TLS_VERSION_MAP.__getitem__
        )
        if tls_min is not None or tls_max is not None:
            min_part = (
                tls_min if tls_min is not None else curl_cffi.CurlSslVersion.DEFAULT
            )
            max_part = (
                (tls_max << 16)
                if tls_max is not None
                else curl_cffi.CurlSslVersion.MAX_DEFAULT
            )
            curl_options[curl_cffi.CurlOpt.SSLVERSION] = min_part | max_part
        self._verify_certificates: bool = verify_certificates
        self._curl_options: dict[curl_cffi.CurlOpt, object] = curl_options
        # https://curl-cffi.readthedocs.io/en/latest/advanced.html#selecting-http-version
        # The mapping is in curl_cffi.requests.utils.normalize_http_version()
        self._http_version: curl_cffi.requests.utils.HttpVersionLiteral = (
            crawler.settings.get("CURL_CFFI_HTTP_VERSION", "v1")
        )
        self._impersonate: (
            curl_cffi.BrowserTypeLiteral | curl_cffi.Fingerprint | None
        ) = None
        if (impersonate := crawler.settings.get("CURL_CFFI_IMPERSONATE")) is not None:
            try:
                self._impersonate = _parse_impersonate(impersonate)
            except ValueError as e:
                raise NotConfigured(f"Invalid CURL_CFFI_IMPERSONATE value: {e}") from e
        # curl_cffi only takes curl options per session, so we keep a session
        # per set of proxy headers. LRU eviction can be added here if needed.
        # Requests impersonating a target by name also get separate sessions,
        # as the browser headers set for them survive curl_easy_reset().
        self._sessions: dict[
            tuple[tuple[tuple[str, str], ...], bool],
            curl_cffi.AsyncSession[curl_cffi.Response],
        ] = {}
        self._warned_socks_proxy_headers: bool = False

    def _make_session(
        self, proxy_headers: tuple[tuple[str, str], ...] = ()
    ) -> curl_cffi.AsyncSession[curl_cffi.Response]:
        curl_options = dict(self._curl_options)
        if proxy_headers:
            curl_options[curl_cffi.CurlOpt.PROXYHEADER] = [
                (f"{name}: {value}" if value else f"{name};").encode()
                for name, value in proxy_headers
            ]
        return curl_cffi.AsyncSession(
            interface=self._get_bind_address_host(),
            allow_redirects=False,
            discard_cookies=True,
            trust_env=False,
            verify=self._verify_certificates,
            default_headers=False,
            # hard limit on simultaneous connections
            max_clients=self._pool_size_total,
            http_version=self._http_version,
            curl_options=curl_options,
        )

    def _get_session(
        self,
        proxy_url: str | None,
        proxy_headers: tuple[tuple[str, str], ...] = (),
        impersonate: str | curl_cffi.Fingerprint | None = None,
    ) -> curl_cffi.AsyncSession[curl_cffi.Response]:
        if not proxy_url:
            proxy_headers = ()
        elif proxy_headers and proxy_url.startswith("socks"):
            if not self._warned_socks_proxy_headers:
                logger.warning(
                    "Ignoring the proxy_headers request metadata key for SOCKS"
                    " proxies, as the SOCKS protocol has no headers."
                )
                self._warned_socks_proxy_headers = True
            proxy_headers = ()
        key = (proxy_headers, isinstance(impersonate, str))
        if (session := self._sessions.get(key)) is None:
            session = self._sessions[key] = self._make_session(proxy_headers)
        return session

    @staticmethod
    def _check_deps_installed() -> None:
        if curl_cffi is None:  # pragma: no cover
            raise NotConfigured(
                "CurlCffiDownloadHandler requires the curl_cffi library to be installed."
            )

    @asynccontextmanager
    async def _make_request(
        self,
        request: Request,
        timeout: float,  # noqa: ASYNC109
    ) -> AsyncIterator[curl_cffi.Response]:
        impersonate = self._impersonate
        if (meta_impersonate := request.meta.get("curl_cffi_impersonate")) is not None:
            impersonate = _parse_impersonate(meta_impersonate)
        proxy = self._extract_proxy_url_with_creds(request)
        session = self._get_session(proxy, get_proxy_headers(request), impersonate)
        headers = curl_cffi.Headers(
            self._utf8_request_headers(request), encoding="utf-8"
        )
        response: curl_cffi.Response | None = None
        try:
            response = await session.request(
                cast("curl_cffi.requests.session.HttpMethod", request.method),
                request.url,
                data=request.body,
                headers=headers,
                # not exactly followed because of how it's implemented in libcurl
                timeout=timeout,
                # don't decompress
                accept_encoding=None,
                proxy=proxy,
                impersonate=impersonate,
                default_headers=impersonate is not None,
                stream=True,
            )
            yield response
        except curl_cffi.requests.exceptions.Timeout as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except curl_cffi.requests.exceptions.InvalidSchema as e:
            raise UnsupportedURLSchemeError(str(e)) from e
        except curl_cffi.requests.exceptions.DNSError as e:
            raise CannotResolveHostError(str(e)) from e
        except (
            curl_cffi.requests.exceptions.SSLError,
            curl_cffi.requests.exceptions.ProxyError,
        ) as e:
            raise DownloadConnectionRefusedError(str(e)) from e
        except curl_cffi.requests.exceptions.ConnectionError as e:
            if e.code in {
                curl_cffi.CurlECode.SEND_ERROR,
                curl_cffi.CurlECode.RECV_ERROR,
                curl_cffi.CurlECode.WEIRD_SERVER_REPLY,
            }:
                raise DownloadFailedError(str(e)) from e
            raise DownloadConnectionRefusedError(str(e)) from e
        except curl_cffi.requests.exceptions.RequestException as e:
            raise DownloadFailedError(str(e)) from e
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
        return Headers(response.headers.raw)

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
        return isinstance(
            exc, curl_cffi.requests.exceptions.RequestException
        ) and exc.code in {
            curl_cffi.CurlECode.PARTIAL_FILE,
            curl_cffi.CurlECode.HTTP2_STREAM,
        }

    async def close(self) -> None:
        for session in self._sessions.values():
            await session.close()


def _parse_impersonate(
    value: curl_cffi.BrowserTypeLiteral | dict[str, Any] | curl_cffi.Fingerprint,
) -> curl_cffi.BrowserTypeLiteral | curl_cffi.Fingerprint:
    if isinstance(value, str):
        target = curl_cffi.requests.impersonate.resolve_latest_browser_type(value)  # type: ignore[no-untyped-call]
        if target not in curl_cffi.FingerprintManager.load_fingerprints():
            raise ValueError(f"Unknown impersonation target: {value!r}")
        return value
    if isinstance(value, dict):
        try:
            return curl_cffi.Fingerprint(**value)
        except TypeError as e:
            raise ValueError(str(e)) from e
    if isinstance(value, curl_cffi.Fingerprint):
        return value
    raise ValueError(f"Expected a target name, a dict or a Fingerprint, got {value!r}")
