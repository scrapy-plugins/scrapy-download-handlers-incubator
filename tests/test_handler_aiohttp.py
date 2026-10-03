from __future__ import annotations

import socket
import sys
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlsplit

import aiohttp
import pytest
from aiohttp.abc import AbstractResolver, ResolveResult
from scrapy import Request
from scrapy.crawler import Crawler

from scrapy_download_handlers_incubator import AiohttpDownloadHandler
from tests.test_handlers_base import (
    TestHttpBase,
    TestHttpProxyBase,
    TestHttpsBase,
    TestHttpsCustomCiphersBase,
    TestHttpsDefaultCiphersBase,
    TestHttpsInvalidDNSIdBase,
    TestHttpsInvalidDNSPatternBase,
    TestHttpsTLSVersionBase,
    TestHttpsWrongHostnameBase,
    TestHttpWithCrawlerBase,
    TestMitmProxyBase,
    TestRealWebsiteBase,
    TestSimpleHttpsBase,
)
from tests.utils.decorators import coroutine_test

if TYPE_CHECKING:
    from scrapy.core.downloader.handlers import DownloadHandlerProtocol

    from tests.mockserver.http import MockServer


class _Resolver(AbstractResolver):
    def __init__(self, crawler: Crawler):
        self.crawler = crawler
        self.closed = False
        self.resolved: list[tuple[str, int]] = []

    @classmethod
    def from_crawler(cls, crawler: Crawler) -> _Resolver:
        return cls(crawler)

    async def resolve(
        self,
        host: str,
        port: int = 0,
        family: socket.AddressFamily = socket.AF_INET,
    ) -> list[ResolveResult]:
        self.resolved.append((host, port))
        return [
            ResolveResult(
                hostname=host,
                host="127.0.0.1",
                port=port,
                family=socket.AF_INET,
                proto=0,
                flags=0,
            )
        ]

    async def close(self) -> None:
        self.closed = True


class AiohttpDownloadHandlerMixin:
    @property
    def download_handler_cls(self) -> type[DownloadHandlerProtocol]:
        return AiohttpDownloadHandler

    @property
    def settings_dict(self) -> dict[str, Any] | None:
        return {
            "DOWNLOAD_HANDLERS": {
                "http": "scrapy_download_handlers_incubator.AiohttpDownloadHandler",
                "https": "scrapy_download_handlers_incubator.AiohttpDownloadHandler",
            }
        }


class TestHttp(AiohttpDownloadHandlerMixin, TestHttpBase):
    handler_supports_bindaddress_meta = False
    handler_bad_header_handling = "fail"

    @pytest.mark.parametrize(
        ("settings", "expected_enabled", "expected_ttl"),
        [
            ({}, True, 10),
            (
                {
                    "AIOHTTP_DNS_CACHE_ENABLED": False,
                    "AIOHTTP_DNS_CACHE_TTL": None,
                },
                False,
                None,
            ),
            ({"AIOHTTP_DNS_CACHE_TTL": "30"}, True, 30),
        ],
    )
    @coroutine_test
    async def test_dns_cache_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
        settings: dict[str, Any],
        expected_enabled: bool,
        expected_ttl: int | None,
    ) -> None:
        connector_kwargs: dict[str, Any] = {}
        connector_cls = aiohttp.TCPConnector

        def connector_factory(**kwargs: Any) -> aiohttp.TCPConnector:
            connector_kwargs.update(kwargs)
            return connector_cls(**kwargs)

        monkeypatch.setattr(aiohttp, "TCPConnector", connector_factory)
        async with self.get_dh(settings):
            assert connector_kwargs["use_dns_cache"] is expected_enabled
            assert connector_kwargs["ttl_dns_cache"] == expected_ttl

    @coroutine_test
    async def test_custom_dns_resolver(self, mockserver: MockServer) -> None:
        server_url = urlsplit(mockserver.url("/text"))
        assert server_url.port is not None
        url = server_url._replace(netloc=f"resolver.invalid:{server_url.port}").geturl()
        async with self.get_dh(
            {"AIOHTTP_DNS_RESOLVER": f"{__name__}._Resolver"}
        ) as download_handler:
            resolver = cast("AiohttpDownloadHandler", download_handler)._resolver
            assert isinstance(resolver, _Resolver)
            assert isinstance(resolver.crawler, Crawler)
            assert resolver.closed is False
            response = await download_handler.download_request(Request(url))
            assert response.body == b"Works"
            assert resolver.resolved == [("resolver.invalid", server_url.port)]
        assert resolver.closed is True


class TestHttps(AiohttpDownloadHandlerMixin, TestHttpsBase):
    handler_supports_bindaddress_meta = False
    handler_bad_header_handling = "fail"
    tls_log_message = "SSL connection to 127.0.0.1 using protocol TLSv1.3, cipher"


class TestSimpleHttps(AiohttpDownloadHandlerMixin, TestSimpleHttpsBase):
    pass


class TestHttpsWrongHostname(AiohttpDownloadHandlerMixin, TestHttpsWrongHostnameBase):
    pass


class TestHttpsInvalidDNSId(AiohttpDownloadHandlerMixin, TestHttpsInvalidDNSIdBase):
    pass


class TestHttpsInvalidDNSPattern(
    AiohttpDownloadHandlerMixin, TestHttpsInvalidDNSPatternBase
):
    pass


class TestHttpsCustomCiphers(AiohttpDownloadHandlerMixin, TestHttpsCustomCiphersBase):
    pass


class TestHttpsDefaultCiphers(AiohttpDownloadHandlerMixin, TestHttpsDefaultCiphersBase):
    pass


class TestHttpsTLSVersion(AiohttpDownloadHandlerMixin, TestHttpsTLSVersionBase):
    pass


class TestHttpWithCrawler(AiohttpDownloadHandlerMixin, TestHttpWithCrawlerBase):
    pass


class TestHttpsWithCrawler(TestHttpWithCrawler):
    is_secure = True


class TestHttpProxy(AiohttpDownloadHandlerMixin, TestHttpProxyBase):
    pass


class TestHttpsProxy(AiohttpDownloadHandlerMixin, TestHttpProxyBase):
    is_secure = True

    @property
    def handler_supports_tls_in_tls(self) -> bool:
        return sys.version_info >= (3, 11)


class TestMitmProxy(AiohttpDownloadHandlerMixin, TestMitmProxyBase):
    handler_supports_socks: bool = False

    @property
    def handler_supports_tls_in_tls(self) -> bool:
        return sys.version_info >= (3, 11)


@pytest.mark.requires_internet
class TestRealWebsite(AiohttpDownloadHandlerMixin, TestRealWebsiteBase):
    pass
