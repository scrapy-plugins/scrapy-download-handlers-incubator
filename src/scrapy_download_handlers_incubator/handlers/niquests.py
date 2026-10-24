from __future__ import annotations

import ipaddress
import logging
from contextlib import asynccontextmanager
from importlib.util import find_spec
from types import MethodType
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlparse

from scrapy.exceptions import (
    CannotResolveHostError,
    DownloadConnectionRefusedError,
    DownloadFailedError,
    DownloadTimeoutError,
    NotConfigured,
    UnsupportedURLSchemeError,
)
from scrapy.http import Headers
from scrapy.utils.python import _iter_exc_causes
from scrapy.utils.ssl import (
    _STDLIB_VERSION_MAP,
    _get_tls_version_limits,
    _make_insecure_ssl_ctx,
)

from scrapy_download_handlers_incubator.utils import get_proxy_headers

from ._base_streaming import BaseStreamingDownloadHandler, _BaseResponseArgs

if TYPE_CHECKING:
    import ssl
    from collections.abc import AsyncIterator

    from scrapy import Request
    from scrapy.crawler import Crawler

HAS_SOCKS = False

try:
    import niquests.adapters
    import niquests.exceptions
    import urllib3.exceptions
except ImportError:
    niquests = None  # type: ignore[assignment]
else:
    HAS_SOCKS = find_spec("python_socks") is not None

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    _Base = BaseStreamingDownloadHandler[niquests.AsyncResponse]
else:
    _Base = BaseStreamingDownloadHandler


class NiquestsDownloadHandler(_Base):
    experimental: ClassVar[bool] = True

    def __init__(self, crawler: Crawler):
        super().__init__(crawler)
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self._verify_certificates: bool = crawler.settings.getbool(
            "DOWNLOAD_VERIFY_CERTIFICATES"
        )
        self._enable_h2: bool = crawler.settings.getbool("NIQUESTS_HTTP2_ENABLED")
        self._tls_limits: tuple[ssl.TLSVersion | None, ssl.TLSVersion | None] = (
            _get_tls_version_limits(crawler.settings, _STDLIB_VERSION_MAP.__getitem__)
        )
        self._session: niquests.AsyncSession = self._make_session()
        # niquests creates a proxy manager, which holds the proxy headers, per
        # proxy URL, so we keep a session per set of proxy headers. LRU
        # eviction can be added here if needed.
        self._proxy_header_sessions: dict[
            tuple[tuple[str, str], ...], niquests.AsyncSession
        ] = {}
        self._warned_socks_proxy_headers: bool = False

    def _make_session(
        self, proxy_headers: tuple[tuple[str, str], ...] = ()
    ) -> niquests.AsyncSession:
        tls_min, tls_max = self._tls_limits
        session = niquests.AsyncSession(
            headers={},
            source_address=self._bind_address,
            disable_http2=not self._enable_h2,
            disable_http3=True,
            # number of host buckets in the pool (older extra ones are discarded)
            pool_connections=self._pool_size_total,
            # number of connections per host in the pool (newer extra ones are not put there)
            pool_maxsize=self._pool_size_per_host,
            allow_incoming_cookies=False,
            verify=self._verify_certificates,
            tls_configuration=niquests.TLSConfiguration(
                min_version=tls_min,
                max_version=tls_max,
            ),
        )
        session.trust_env = False
        if not self._verify_certificates:
            # Ugly hack to skip proxy certificate verification, may be not worth it.
            # The official docs suggest passing the CA bundle via an envvar but that
            # doesn't work with trust_env=False.
            orig_proxy_manager_for = (
                niquests.adapters.AsyncHTTPAdapter.proxy_manager_for
            )

            def proxy_manager_for_no_verify(
                self_: niquests.adapters.AsyncHTTPAdapter,
                proxy: str,
                **proxy_kwargs: Any,
            ) -> urllib3.AsyncProxyManager:
                proxy_ctx = _make_insecure_ssl_ctx()
                proxy_kwargs["ssl_context"] = proxy_ctx
                return orig_proxy_manager_for(self_, proxy, **proxy_kwargs)  # type: ignore[no-any-return]

            for adapter in session.adapters.values():
                if isinstance(adapter, niquests.adapters.AsyncHTTPAdapter):
                    adapter.proxy_manager_for = MethodType(  # type: ignore[method-assign]
                        proxy_manager_for_no_verify, adapter
                    )
        if proxy_headers:
            # urllib3 encodes proxy header values as latin-1
            extra_headers: dict[str, str] = {}
            for name, value in proxy_headers:
                latin1_value = value.encode().decode("latin-1")
                if name in extra_headers:
                    extra_headers[name] += f",{latin1_value}"
                else:
                    extra_headers[name] = latin1_value
            extra_names = {name.lower() for name in extra_headers}
            orig_proxy_headers = niquests.adapters.AsyncHTTPAdapter.proxy_headers

            def proxy_headers_with_extra(
                self_: niquests.adapters.AsyncHTTPAdapter, proxy: str
            ) -> dict[str, str]:
                headers = {
                    name: value
                    for name, value in orig_proxy_headers(self_, proxy).items()
                    if name.lower() not in extra_names
                }
                headers.update(extra_headers)
                return headers

            for adapter in session.adapters.values():
                if isinstance(adapter, niquests.adapters.AsyncHTTPAdapter):
                    adapter.proxy_headers = MethodType(  # type: ignore[method-assign]
                        proxy_headers_with_extra, adapter
                    )
        return session

    def _get_session(
        self,
        proxy_url: str | None,
        proxy_headers: tuple[tuple[str, str], ...] = (),
    ) -> niquests.AsyncSession:
        if not proxy_url or not proxy_headers:
            return self._session
        if proxy_url.startswith("socks"):
            if not self._warned_socks_proxy_headers:
                logger.warning(
                    "Ignoring the proxy_headers request metadata key for SOCKS"
                    " proxies, as the SOCKS protocol has no headers."
                )
                self._warned_socks_proxy_headers = True
            return self._session
        if cached := self._proxy_header_sessions.get(proxy_headers):
            return cached
        session = self._make_session(proxy_headers)
        self._proxy_header_sessions[proxy_headers] = session
        return session

    @staticmethod
    def _check_deps_installed() -> None:
        if niquests is None:  # pragma: no cover
            raise NotConfigured(
                "NiquestsDownloadHandler requires the niquests library to be installed."
            )

    @asynccontextmanager
    async def _make_request(
        self,
        request: Request,
        timeout: float,  # noqa: ASYNC109
    ) -> AsyncIterator[niquests.AsyncResponse]:
        proxy = self._extract_proxy_url_with_creds(request)
        if proxy and proxy.startswith("socks") and not HAS_SOCKS:  # pragma: no cover
            raise ValueError(
                f"SOCKS proxy support in {type(self).__name__} requires the 'niquests[socks]' extra to be installed."
            )
        headers = {
            name: b",".join(values)
            for name, values in self._request_headers(request).items()
            if values
        }
        proxies = {"http": proxy, "https": proxy} if proxy else None
        session = self._get_session(proxy, get_proxy_headers(request))
        try:
            async with await session.request(
                method=request.method,
                url=request.url,
                data=request.body,
                headers=headers,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
                proxies=proxies,
            ) as nq_response:
                yield nq_response
        except niquests.ReadTimeout as e:
            raise DownloadTimeoutError(
                f"Getting {request.url} took longer than {timeout} seconds."
            ) from e
        except niquests.exceptions.InvalidSchema as e:
            raise UnsupportedURLSchemeError(str(e)) from e
        except niquests.ConnectionError as e:
            for c in _iter_exc_causes(e):
                match c:
                    case urllib3.exceptions.NameResolutionError():
                        raise CannotResolveHostError(str(e)) from e
                    case urllib3.exceptions.NewConnectionError():
                        raise DownloadConnectionRefusedError(str(e)) from e
                    case (
                        urllib3.exceptions.ConnectTimeoutError()
                        | urllib3.exceptions.ReadTimeoutError()
                    ):
                        raise DownloadTimeoutError(str(e)) from e
            raise DownloadFailedError(str(e)) from e
        except (
            niquests.RequestException,
            urllib3.exceptions.HTTPError,
        ) as e:
            raise DownloadFailedError(str(e)) from e

    @staticmethod
    def _extract_headers(response: niquests.AsyncResponse) -> Headers:
        # response.headers is niquests.structures.CaseInsensitiveDict which
        # doesn't support multiple values, response.raw.headers is
        # urllib3.HTTPHeaderDict which supports them
        assert isinstance(response.raw, urllib3.HTTPResponse)
        assert isinstance(response.raw.headers, urllib3.HTTPHeaderDict)
        # the values are decoded as latin-1, so encoding them back gives the
        # received bytes
        return Headers(
            [
                (name.encode("latin-1"), value.encode("latin-1"))
                for name, value in response.raw.headers.items()
            ]
        )

    @staticmethod
    def _build_base_response_args(
        response: niquests.AsyncResponse,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        assert response.conn_info is not None
        ip_address = None
        if response.conn_info.destination_address:
            ip_address = ipaddress.ip_address(response.conn_info.destination_address[0])
        protocol = None
        if response.conn_info.http_version:
            protocol = response.conn_info.http_version.value
        assert response.status_code is not None
        return {
            "status": response.status_code,
            "url": request.url,
            "headers": headers,
            "certificate": response.conn_info.certificate_der,
            "ip_address": ip_address,
            "protocol": protocol,
        }

    @staticmethod
    async def _iter_body_chunks(
        response: niquests.AsyncResponse,
    ) -> AsyncIterator[bytes]:
        async for chunk in await response.iter_raw():
            yield chunk

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return isinstance(exc, niquests.exceptions.ChunkedEncodingError)

    def _log_tls_info(self, response: niquests.AsyncResponse, request: Request) -> None:
        conn_info = response.conn_info
        if conn_info and conn_info.tls_version:
            logger.debug(
                f"SSL connection to {urlparse(request.url).hostname}"
                f" using protocol {conn_info.tls_version.name},"
                f" cipher {conn_info.cipher}"
            )
            if cert := conn_info.certificate_dict:
                logger.debug(
                    f"SSL connection certificate: issuer {cert['issuer']}, subject {cert['subject']}"
                )

    async def close(self) -> None:
        await self._session.close()
        for session in self._proxy_header_sessions.values():
            await session.close()
