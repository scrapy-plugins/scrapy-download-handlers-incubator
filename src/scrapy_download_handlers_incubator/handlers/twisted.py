"""Twisted-based HTTP(S) download handler. Currently not recommended for production use.

A reimplementation of the default Scrapy download handler,
:class:`scrapy.core.downloader.handlers.http11.HTTP11DownloadHandler`, on top
of :class:`~scrapy.core.downloader.handlers._base_streaming.BaseStreamingDownloadHandler`.
"""

from __future__ import annotations

import ipaddress
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, ClassVar, cast
from urllib.parse import urldefrag, urlparse

from OpenSSL import SSL
from scrapy.core.downloader.contextfactory import _load_context_factory_from_settings
from scrapy.core.downloader.handlers._base_streaming import (
    BaseStreamingDownloadHandler,
    _BaseResponseArgs,
)
from scrapy.core.downloader.handlers.http11 import (
    _RequestBodyProducer,
    _ScrapyProxyAgent,
    _TunnelingAgent,
)
from scrapy.exceptions import DownloadTimeoutError, NotConfigured
from scrapy.http import Headers
from scrapy.utils._download_handlers import (
    normalize_bind_address,
    wrap_twisted_exceptions,
)
from scrapy.utils.defer import maybe_deferred_to_future
from scrapy.utils.httpobj import urlparse_cached
from scrapy.utils.python import to_bytes, to_unicode
from scrapy.utils.reactor import is_reactor_installed
from scrapy.utils.ssl import _log_ssl_conn_debug_info
from scrapy.utils.url import add_http_if_no_scheme
from twisted.internet import ssl
from twisted.internet.defer import DeferredQueue
from twisted.internet.protocol import Protocol, connectionDone
from twisted.python.failure import Failure
from twisted.web.client import Agent, HTTPConnectionPool, ResponseDone, ResponseFailed
from twisted.web.http import PotentialDataLoss, _DataLoss
from twisted.web.http_headers import Headers as TxHeaders
from twisted.web.iweb import UNKNOWN_LENGTH

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from ipaddress import IPv4Address, IPv6Address

    from scrapy import Request
    from scrapy.crawler import Crawler
    from twisted.internet.defer import Deferred
    from twisted.web.client import Response as TxResponse
    from twisted.web.iweb import IBodyProducer, IPolicyForHTTPS


def _is_dataloss(exc: BaseException) -> bool:
    return isinstance(exc, ResponseFailed) and any(
        r.check(_DataLoss) for r in exc.reasons
    )


class _TwistedResponse:
    """The Twisted response with the related data and helpers."""

    def __init__(self, txresponse: TxResponse, timeout_msg: str):
        self.txresponse: TxResponse = txresponse
        self.timeout_msg: str = timeout_msg
        self.queue: DeferredQueue[bytes | Failure | None] = DeferredQueue()
        self.certificate: ssl.Certificate | None = None
        self.ip_address: IPv4Address | IPv6Address | None = None
        self.tls_connection: SSL.Connection | None = None
        self.no_body: bool = False
        self.timed_out: bool = False
        self.finished: bool = False
        self._aborted: bool = False
        # As this runs synchronously when the response headers are parsed, the
        # transport info is still available here even if the (small) response
        # body arrived in the same reactor iteration.
        self._capture_conn_info()

    def _capture_conn_info(self) -> None:
        producer = self.txresponse._transport._producer
        if producer is None:
            # Already detached, e.g. for responses without a body.
            return
        with suppress(AttributeError):
            self.certificate = ssl.Certificate(  # type: ignore[no-untyped-call]
                producer.getPeerCertificate()
            )
        with suppress(AttributeError):
            self.ip_address = ipaddress.ip_address(producer.getPeer().host)
        with suppress(AttributeError):
            connection = producer.getHandle()
            if isinstance(connection, SSL.Connection):
                self.tls_connection = connection

    def mark_timed_out(self) -> None:
        self.timed_out = True
        # Wake up a pending queue.get(); the value is irrelevant as
        # _iter_body_chunks() checks timed_out first.
        self.queue.put(None)
        self.abort()

    def abort(self) -> None:
        """Abort the connection unless the response was fully received."""
        if self.finished or self._aborted:
            return
        self._aborted = True
        transport = self.txresponse._transport
        producer = transport._producer
        with suppress(AttributeError):
            transport.stopProducing()
        if producer is not None:
            producer.abortConnection()


class _StreamReader(Protocol):
    """A protocol that puts the received response body data into a queue."""

    def __init__(self, response: _TwistedResponse):
        self._response: _TwistedResponse = response

    def dataReceived(self, data: bytes) -> None:
        # This may be called with buffered data even after the download was
        # finished early.
        if self._response.finished:
            return
        self._response.queue.put(data)

    def connectionLost(self, reason: Failure = connectionDone) -> None:
        if self._response.finished:
            return
        self._response.finished = True
        if reason.check(ResponseDone, PotentialDataLoss):  # type: ignore[no-untyped-call]
            # PotentialDataLoss (a response delimited by the connection close)
            # is treated as a clean end of the body: the "partial" response
            # flag that HTTP11DownloadHandler sets in this case is not
            # supported by BaseStreamingDownloadHandler.
            self._response.queue.put(None)
        else:
            self._response.queue.put(reason)


class TwistedDownloadHandler(BaseStreamingDownloadHandler[_TwistedResponse]):
    experimental: ClassVar[bool] = True
    requires_asyncio: ClassVar[bool] = False
    supports_per_request_bindaddress: ClassVar[bool] = True

    def __init__(self, crawler: Crawler):
        if not crawler.settings.getbool("TWISTED_REACTOR_ENABLED"):
            raise NotConfigured(f"{type(self).__name__} requires a Twisted reactor.")
        super().__init__(crawler)

        from twisted.internet import reactor

        self._pool: HTTPConnectionPool = HTTPConnectionPool(  # type: ignore[no-untyped-call]
            reactor, persistent=True
        )
        self._pool.maxPersistentPerHost = self._pool_size_per_host
        self._pool._factory.noisy = False
        self._context_factory: IPolicyForHTTPS = _load_context_factory_from_settings(
            crawler
        )
        self._disconnect_timeout: int = 1

    @staticmethod
    def _check_deps_installed() -> None:
        if not is_reactor_installed():  # pragma: no cover
            raise NotConfigured(
                "TwistedDownloadHandler requires an installed Twisted reactor."
            )

    def _get_agent(self, request: Request, timeout: float) -> Agent:
        from twisted.internet import reactor

        bindaddress = normalize_bind_address(
            request.meta.get("bindaddress") or self._bind_address
        )
        proxy = request.meta.get("proxy")
        if proxy:
            proxy = add_http_if_no_scheme(proxy)
            proxy_parsed = urlparse(proxy)
            proxy_host = proxy_parsed.hostname
            proxy_port = proxy_parsed.port
            if not proxy_port:
                proxy_port = 443 if proxy_parsed.scheme == "https" else 80
            if urlparse_cached(request).scheme == "https":
                if proxy_parsed.scheme == "https":
                    raise NotImplementedError(
                        "HTTPS proxies for HTTPS destinations are not supported"
                    )
                assert proxy_host is not None
                proxy_auth = request.headers.get(b"Proxy-Authorization", None)
                return _TunnelingAgent(
                    reactor=reactor,
                    proxyConf=(proxy_host, proxy_port, proxy_auth),
                    contextFactory=self._context_factory,
                    connectTimeout=timeout,
                    bindAddress=bindaddress,
                    pool=self._pool,
                )
            return _ScrapyProxyAgent(
                reactor=reactor,
                proxyURI=to_bytes(proxy, encoding="ascii"),
                contextFactory=self._context_factory,
                connectTimeout=timeout,
                bindAddress=bindaddress,
                pool=self._pool,
            )
        return Agent(  # type: ignore[no-untyped-call]
            reactor=reactor,
            contextFactory=self._context_factory,
            connectTimeout=timeout,
            bindAddress=bindaddress,
            pool=self._pool,
        )

    @asynccontextmanager
    async def _make_request(
        self, request: Request, timeout: float
    ) -> AsyncIterator[_TwistedResponse]:
        from twisted.internet import reactor

        agent = self._get_agent(request, timeout)
        url = urldefrag(request.url)[0]
        tx_headers = TxHeaders(request.headers)
        if isinstance(agent, _TunnelingAgent):
            tx_headers.removeHeader(b"Proxy-Authorization")
        body_producer = _RequestBodyProducer(request.body) if request.body else None
        timeout_msg = f"Getting {url} took longer than {timeout} seconds."

        response: _TwistedResponse | None = None
        timed_out = False

        def wrap_response(txresponse: TxResponse) -> _TwistedResponse:
            # This callback runs synchronously when the response headers are
            # parsed, which is required for _capture_conn_info() to work.
            nonlocal response
            response = _TwistedResponse(txresponse, timeout_msg)
            return response

        def on_timeout() -> None:
            nonlocal timed_out
            timed_out = True
            if response is None:
                d.cancel()
            else:
                response.mark_timed_out()

        with wrap_twisted_exceptions():
            d: Deferred[_TwistedResponse] = agent.request(
                to_bytes(request.method),
                to_bytes(url, encoding="ascii"),
                headers=tx_headers,
                bodyProducer=cast("IBodyProducer", body_producer),
            ).addCallback(wrap_response)
        timeout_call = reactor.callLater(timeout, on_timeout) if timeout else None
        try:
            try:
                with wrap_twisted_exceptions():
                    result = await maybe_deferred_to_future(d)
            except Exception as e:
                if timed_out:
                    raise DownloadTimeoutError(timeout_msg) from e
                raise
            if timed_out:
                raise DownloadTimeoutError(timeout_msg)
            if cast("int", result.txresponse.length) == 0:
                # deliverBody() hangs for responses without a body.
                result.no_body = True
                result.finished = True
            else:
                result.txresponse.deliverBody(  # type: ignore[no-untyped-call]
                    _StreamReader(result)
                )
            yield result
        finally:
            if timeout_call is not None and timeout_call.active():
                timeout_call.cancel()
            if response is not None:
                response.abort()

    @staticmethod
    def _extract_headers(response: _TwistedResponse) -> Headers:
        headers = Headers()
        # Twisted moves some headers, including Content-Length, out of
        # response.headers, so this needs to be restored from response.length.
        if response.txresponse.length != UNKNOWN_LENGTH:
            headers[b"Content-Length"] = str(response.txresponse.length).encode()
        headers.update(response.txresponse.headers.getAllRawHeaders())
        return headers

    @staticmethod
    def _build_base_response_args(
        response: _TwistedResponse,
        request: Request,
        headers: Headers,
    ) -> _BaseResponseArgs:
        protocol: str | None
        try:
            version = response.txresponse.version
            protocol = f"{to_unicode(version[0])}/{version[1]}.{version[2]}"
        except (AttributeError, TypeError, IndexError):
            protocol = None
        return {
            "status": int(response.txresponse.code),
            "url": request.url,
            "headers": headers,
            "certificate": response.certificate,
            "ip_address": response.ip_address,
            "protocol": protocol,
        }

    def _log_tls_info(self, response: _TwistedResponse, request: Request) -> None:
        if response.tls_connection is None:
            return
        hostname = urlparse_cached(request).hostname
        assert hostname is not None
        _log_ssl_conn_debug_info(hostname, response.tls_connection)

    @staticmethod
    async def _iter_body_chunks(response: _TwistedResponse) -> AsyncIterator[bytes]:
        if response.no_body:
            return
        while True:
            item = await maybe_deferred_to_future(response.queue.get())
            if response.timed_out:
                raise DownloadTimeoutError(response.timeout_msg)
            if item is None:
                # The response body was fully received.
                return
            if not isinstance(item, Failure):
                yield item
                continue
            if item.value is not None and _is_dataloss(item.value):
                # Raised unwrapped so that _is_dataloss_exception() can
                # detect it.
                item.raiseException()
            with wrap_twisted_exceptions():
                item.raiseException()

    @staticmethod
    def _is_dataloss_exception(exc: Exception) -> bool:
        return _is_dataloss(exc)

    async def close(self) -> None:
        from twisted.internet import reactor

        d: Deferred[None] = self._pool.closeCachedConnections()  # type: ignore[no-untyped-call]
        # closeCachedConnections will hang on network or server issues, so
        # we'll manually timeout the deferred.
        #
        # Twisted issue addressing this problem can be found here:
        # https://github.com/twisted/twisted/issues/7738
        #
        # closeCachedConnections doesn't handle external errbacks, so we'll
        # issue a callback after `_disconnect_timeout` seconds.
        #
        # See also https://github.com/scrapy/scrapy/issues/2653
        delayed_call = reactor.callLater(self._disconnect_timeout, d.callback, ())
        try:
            await maybe_deferred_to_future(d)
        finally:
            if delayed_call.active():
                delayed_call.cancel()
