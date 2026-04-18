from __future__ import annotations

import logging
import ssl
from http.cookiejar import Cookie, CookieJar
from typing import TYPE_CHECKING

from scrapy.utils.ssl import _log_sslobj_debug_info

if TYPE_CHECKING:
    from http.client import HTTPResponse
    from urllib.request import Request as ULRequest

logger = logging.getLogger(__name__)


class NullCookieJar(CookieJar):  # pragma: no cover
    """A CookieJar that rejects all cookies."""

    def extract_cookies(self, response: HTTPResponse, request: ULRequest) -> None:
        pass

    def set_cookie(self, cookie: Cookie) -> None:
        pass


def make_insecure_ssl_ctx() -> ssl.SSLContext:
    """Create an SSL context that doesn't verify certificates.

    Compared to :func:`~scrapy.utils.ssl._make_ssl_context` this is much more
    simple.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def log_sslobj_debug_info(sslobj: ssl.SSLObject) -> None:
    _log_sslobj_debug_info(sslobj)
    if cert := sslobj.getpeercert():
        # Not available without certificate verification
        logger.debug(
            f"SSL connection certificate: issuer {cert['issuer']}, subject {cert['subject']}"
        )
