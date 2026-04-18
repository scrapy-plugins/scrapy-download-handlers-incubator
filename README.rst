Overview
========

This is a collection of semi-official download handlers for Scrapy_. See the
`Scrapy download handler`_ documentation for more information.

They should work and some of them may be later promoted to the official status,
but here they are provided as-is and no support or stability promises are
given. The documentation, including limitations and unsupported features, is
also provided as-is and may be incomplete.

As this code may intentionally use private Scrapy APIs, it specifies a tight
dependency on Scrapy. Currently only the unreleased 2.15.0 version is
supported.

.. _Scrapy: https://scrapy.org/
.. _Scrapy download handler: https://docs.scrapy.org/en/latest/topics/download-handlers.html

Features overview
=================

The baseline for these handlers is the default Scrapy handler,
``HTTP11DownloadHandler``, which uses Twisted and supports HTTP/1.1. Feature
parity with it is an explicit goal but it's not always possible and not all
possible features are implemented in all handlers (which may change in the
future). Certain popular features not supported by ``HTTP11DownloadHandler``,
like HTTP/2 support, and features unique to some handlers, may or may not be
implemented. Please see the sections for individual handlers for more details.

The following table summarizes the most important differences:

========================= ============ ================ ============ ============ ============= ==================
Handler                   HTTP/2       HTTP/3           Proxies      TLS logging  Impersonation TLS version limits
========================= ============ ================ ============ ============ ============= ==================
(HTTP11DownloadHandler)   Not possible Not possible     Yes          Yes          Not possible  No
AiohttpDownloadHandler    Not possible Not possible     Yes          Partial      Not possible  No
CurlCffiDownloadHandler   Yes          Yes (not tested) Yes          Not possible No            Not possible
HttpxDownloadHandler      Yes          Not possible     Yes          Yes          Not possible  No
NiquestsDownloadHandler   Yes          No               Yes          Yes          Not possible  Not possible
PyreqwestDownloadHandler  Yes          Not possible     Not possible Not possible Not possible  No
========================= ============ ================ ============ ============ ============= ==================

The following basic features are supported by all handlers unless mentioned in
their docs:

* Native asyncio integration without requiring a Twisted reactor
* HTTP/1.1 for ``http`` and ``https`` schemes
* Unified download handler exceptions
* Proxies, including HTTP and HTTPS proxies for HTTP and HTTPS destinations
* Proxy authentication via ``HttpProxyMiddleware``
* IPv6 destinations
* ``DOWNLOAD_MAXSIZE``, ``DOWNLOAD_WARNSIZE`` and the respective request meta
  keys
* ``DOWNLOAD_TIMEOUT`` and the respective request meta key
* ``DOWNLOAD_FAIL_ON_DATALOSS`` and the ``"dataloss"`` flag
* Setting the ``download_latency`` request meta
* ``DOWNLOAD_BIND_ADDRESS``
* ``DOWNLOAD_VERIFY_CERTIFICATES``
* ``headers_received`` and ``bytes_received`` signals
* Not reading the proxy configuration from the environment variables
* Not handling cookies, redirects, compression and other things handled by
  Scrapy itself

Handlers
========

AiohttpDownloadHandler
----------------------

This handler supports HTTP/1.1 and uses the aiohttp_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[aiohttp]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.AiohttpDownloadHandler",
        "https": "scrapy_download_handlers_incubator.AiohttpDownloadHandler",
    }

Features and limitations
^^^^^^^^^^^^^^^^^^^^^^^^

============================== =============================================================================
Proxies                        Yes (HTTPS proxies for HTTPS destinations are not supported on Python < 3.11)
HTTP/2                         No (not supported by the library)
TLS verbose logging            Partial (skipped for small responses)
``response.ip_address``        Partial (skipped for small responses)
``response.certificate``       Partial (DER bytes; skipped for small responses)
Per-request ``bindaddress``    No (not supported by the library)
Proxy certificate verification Follows ``DOWNLOAD_VERIFY_CERTIFICATES``
============================== =============================================================================

Notable features supported by the library but not implemented:

* DNS resolving settings
* Custom DNS resolvers

.. _aiohttp: https://docs.aiohttp.org/en/stable/

CurlCffiDownloadHandler
-----------------------

This handler supports HTTP/1.1 and HTTP/2 and uses the curl_cffi_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[curl-cffi]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.CurlCffiDownloadHandler",
        "https": "scrapy_download_handlers_incubator.CurlCffiDownloadHandler",
    }

Features and limitations
^^^^^^^^^^^^^^^^^^^^^^^^

============================== ========================================
Proxies                        Yes
HTTP/2                         Yes
HTTP/3                         Yes (but not tested)
TLS verbose logging            No (not supported by the library)
``response.ip_address``        Yes
``response.certificate``       No (not supported by the library)
Per-request ``bindaddress``    No (not supported by the library)
Proxy certificate verification Follows ``DOWNLOAD_VERIFY_CERTIFICATES``
============================== ========================================

Notable features supported by the library but not implemented:

* Impersonation
* Advanced libcurl tunables

Settings
^^^^^^^^

* ``CURL_CFFI_HTTP_VERSION`` (``str``, default: ``"v1"``, corresponding to
  "Enforce HTTP/1.1"): The HTTP version to use. The value is passed directly to
  the library so the possible values are set by
  ``curl_cffi.requests.utils.normalize_http_version()`` and the meanings of the
  underlying constants can be seen in libcurl docs (CURLOPT_HTTP_VERSION_). Set
  this to ``"v2tls"`` or ``"v2"`` to enable HTTP/2 for HTTPS requests or for
  all requests respectively. Set this to ``"v3"`` to enable HTTP/3.

.. _curl_cffi: https://curl-cffi.readthedocs.io/en/latest/
.. _CURLOPT_HTTP_VERSION: https://curl.se/libcurl/c/CURLOPT_HTTP_VERSION.html

HttpxDownloadHandler
--------------------

This is an updated copy of the official
``scrapy.core.downloader.handlers._httpx.HttpxDownloadHandler`` handler. It
supports HTTP/1.1 and HTTP/2 and uses the httpx_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[httpx]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.HttpxDownloadHandler",
        "https": "scrapy_download_handlers_incubator.HttpxDownloadHandler",
    }

Features and limitations
^^^^^^^^^^^^^^^^^^^^^^^^

============================== ========================================
Proxies                        Yes (separate connection pool per proxy)
HTTP/2                         Yes
HTTP/3                         No (not supported by the library)
TLS verbose logging            Yes
``response.ip_address``        Yes
``response.certificate``       Yes (DER bytes)
Per-request ``bindaddress``    No (not supported by the library)
Proxy certificate verification Follows ``DOWNLOAD_VERIFY_CERTIFICATES``
============================== ========================================

Notable features supported by the library but not implemented:

* SOCKS5 proxies
* Alternative transports
* Limiting the number of per-proxy connection pool to save resources

Settings
^^^^^^^^

* ``HTTPX_HTTP2_ENABLED`` (``bool``, default: ``False``): Whether to enable
  HTTP/2.

.. _httpx: https://www.python-httpx.org/

NiquestsDownloadHandler
-----------------------

This handler supports HTTP/1.1 and HTTP/2 and uses the niquests_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[niquests]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.NiquestsDownloadHandler",
        "https": "scrapy_download_handlers_incubator.NiquestsDownloadHandler",
    }

Features and limitations
^^^^^^^^^^^^^^^^^^^^^^^^

============================== ========================================
Proxies                        Yes
HTTP/2                         Yes
HTTP/3                         No (not implemented)
TLS verbose logging            Yes
``response.ip_address``        Yes
``response.certificate``       Yes (DER bytes)
Per-request ``bindaddress``    No (not supported by the library)
Proxy certificate verification Follows ``DOWNLOAD_VERIFY_CERTIFICATES``
============================== ========================================

Notable features supported by the library but not implemented:

* Custom DNS resolvers
* SOCKS5 proxies
* HTTP/2 tunables

Settings
^^^^^^^^

* ``NIQUESTS_HTTP2_ENABLED`` (``bool``, default: ``False``): Whether to enable
  HTTP/2.

.. _niquests: https://niquests.readthedocs.io/en/latest/

PyreqwestDownloadHandler
------------------------

This handler supports HTTP/1.1 and HTTP/2 and uses the pyreqwest_ library.

Install it with:

.. code:: bash

    pip install scrapy-download-handlers-incubator[pyreqwest]

Enable it with:

.. code-block:: python

    DOWNLOAD_HANDLERS = {
        "http": "scrapy_download_handlers_incubator.PyreqwestDownloadHandler",
        "https": "scrapy_download_handlers_incubator.PyreqwestDownloadHandler",
    }

Features and limitations
^^^^^^^^^^^^^^^^^^^^^^^^

=========================== =================================
Proxies                     No (not supported by the library)
HTTP/2                      Yes
HTTP/3                      No (not supported by the library)
TLS verbose logging         No (not supported by the library)
``response.ip_address``     No (not supported by the library)
``response.certificate``    No (not supported by the library)
Per-request ``bindaddress`` No (not supported by the library)
=========================== =================================

Notable features supported by the library but not implemented:

* HTTP/2 tunables

Settings
^^^^^^^^

* ``PYREQWEST_HTTP2_ENABLED`` (``bool``, default: ``False``): Whether to enable
  HTTP/2.

.. _pyreqwest: https://markussintonen.github.io/pyreqwest/pyreqwest.html
