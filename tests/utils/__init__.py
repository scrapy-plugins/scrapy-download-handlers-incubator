from __future__ import annotations

import contextlib
import os
import socket
from importlib.metadata import version
from pathlib import Path

from packaging.version import Version

try:
    socket.getaddrinfo("non-existing-host", 80)
    NON_EXISTING_RESOLVABLE = True
except socket.gaierror:
    NON_EXISTING_RESOLVABLE = False


# Hostnames rejected by the idna package but resolvable in practice: the
# punycode form of an emoji domain (i❤.ws) and a domain with an underscore.
IDNA_REJECTED_HOSTNAMES = ["xn--i-7iq.ws", "foo_bar.example"]

# safe_url_string() drops the brackets of an IPv6 address literal in the
# netloc, https://github.com/scrapy/w3lib/pull/253
# (scrapy.utils._deps_compat.W3LIB_STRIPS_IPV6_BRACKETS in Scrapy 2.20+)
W3LIB_STRIPS_IPV6_BRACKETS = (
    Version("2.0.0") <= Version(version("w3lib")) < Version("2.4.1")
)


def get_script_run_env() -> dict[str, str]:
    """Return a OS environment dict suitable to run scripts shipped with tests."""

    tests_path = Path(__file__).parent.parent
    pythonpath = str(tests_path) + os.pathsep + os.environ.get("PYTHONPATH", "")
    env = os.environ.copy()
    env["PYTHONPATH"] = pythonpath
    return env


def ipv6_loopback_available() -> bool:
    """Return True if the IPv6 loopback address (``::1``) can be bound on this host.

    Meant to be used in skip conditions::

        @pytest.mark.skipif(
            not ipv6_loopback_available(), reason="IPv6 loopback is not available"
        )
    """
    if not getattr(socket, "has_ipv6", False):
        return False
    try:
        with contextlib.closing(
            socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        ) as s:
            with contextlib.suppress(OSError, AttributeError):
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s.bind(("::1", 0))
        return True
    except OSError:
        return False
