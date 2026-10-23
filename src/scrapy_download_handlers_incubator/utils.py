from __future__ import annotations

from typing import TYPE_CHECKING

from scrapy.http import Headers

if TYPE_CHECKING:
    from scrapy import Request


# scrapy.utils._download_handlers.get_proxy_headers() in Scrapy 2.20+
def get_proxy_headers(request: Request) -> tuple[tuple[str, str], ...]:
    """Return the headers to send to the proxy, from the ``proxy_headers``
    request metadata key, as name-value pairs.

    Pairs are sorted so that handlers that key their connections on them treat
    header sets that only differ in order as the same set.
    """
    proxy_headers = request.meta.get("proxy_headers")
    if not proxy_headers:
        return ()
    return tuple(sorted(Headers(proxy_headers).to_tuple_list()))
