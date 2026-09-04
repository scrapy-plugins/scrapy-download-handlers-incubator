from __future__ import annotations

import os
import socket
from pathlib import Path

try:
    socket.getaddrinfo("non-existing-host", 80)
    NON_EXISTING_RESOLVABLE = True
except socket.gaierror:
    NON_EXISTING_RESOLVABLE = False


# Hostnames rejected by the idna package but resolvable in practice: the
# punycode form of an emoji domain (i❤.ws) and a domain with an underscore.
IDNA_REJECTED_HOSTNAMES = ["xn--i-7iq.ws", "foo_bar.example"]


def get_script_run_env() -> dict[str, str]:
    """Return a OS environment dict suitable to run scripts shipped with tests."""

    tests_path = Path(__file__).parent.parent
    pythonpath = str(tests_path) + os.pathsep + os.environ.get("PYTHONPATH", "")
    env = os.environ.copy()
    env["PYTHONPATH"] = pythonpath
    return env
