from __future__ import annotations

from http.cookiejar import Cookie, CookieJar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from http.client import HTTPResponse
    from urllib.request import Request as ULRequest


class NullCookieJar(CookieJar):  # pragma: no cover
    """A CookieJar that rejects all cookies."""

    def extract_cookies(self, response: HTTPResponse, request: ULRequest) -> None:
        pass

    def set_cookie(self, cookie: Cookie) -> None:
        pass
