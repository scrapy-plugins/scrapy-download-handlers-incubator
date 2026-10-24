=========
Changelog
=========

0.6.0 (2026-10-24)
------------------

* Dropped support for Scrapy 2.18.x.
* Dropped support for Python 3.10.
* Dropped support for the original ``httpx`` library in
  ``HttpxDownloadHandler``, it now requires ``httpx2``. The ``httpx`` extra
  now installs ``httpx2``, the ``httpx2`` extra was removed.
* Bumped the minimum supported ``curl_cffi`` version to 0.16.0.
* Bumped the minimum supported ``httpx2`` version to 2.3.0.
* Added ``aiodns`` to the dependencies.
* Removed the ``aiohttp`` extra as ``aiohttp`` is a dependency of Scrapy.
* Synced some of the ``AiohttpDownloadHandler`` and ``HttpxDownloadHandler``
  changes from unreleased Scrapy 2.20.0.
* Added support for the ``proxy_headers`` request meta key to
  ``CurlCffiDownloadHandler`` and ``NiquestsDownloadHandler``.
* Improved handling of request and response headers that are not ASCII or
  UTF-8 in ``CurlCffiDownloadHandler``, ``NiquestsDownloadHandler`` and
  ``PyreqwestDownloadHandler``.
* CI improvements.

0.5.1 (2026-09-12)
------------------

This is the last version that supports Scrapy 2.18.x.

* Added support for Scrapy 2.19.x.

0.5.0 (2026-09-04)
------------------

This is the last version that supports Scrapy 2.17.x.

* Importing the top-level package no longer tries to import all handler
  modules, those are now imported lazily.
* Synced ``HttpxDownloadHandler`` changes from Scrapy.
* CI improvements.

0.4.1 (2026-08-20)
------------------

* Added support for Scrapy 2.18.x.

0.4.0 (2026-07-11)
------------------

* Dropped support for Scrapy 2.16.x.
* Bumped the minimum supported ``niquests`` version to 3.20.0.
* Added support for the ``DOWNLOAD_TLS_MIN_VERSION`` and
  ``DOWNLOAD_TLS_MAX_VERSION`` settings to all handlers.
* Added support for the ``verbatim_url`` request meta key to
  ``AiohttpDownloadHandler``.
* CI improvements.

0.3.0 (2026-07-08)
------------------

This is the last version that supports Scrapy 2.16.x.

* Added support for Scrapy 2.17.x.
* Bumped the minimum supported ``aiohttp`` version to 3.13.3.
* Added support for the ``httpx2`` library to ``HttpxDownloadHandler``.
* Fixed handling of the ``Proxy-Authorization`` header.
* Documentation improvements.
* CI improvements.

0.2.0 (2026-05-30)
------------------

* Dropped support for Scrapy 2.15.x.
* Added SOCKS proxy support to ``CurlCffiDownloadHandler``,
  ``HttpxDownloadHandler`` and ``NiquestsDownloadHandler``.
* Fixed getting TLS and server IP information for short responses in
  ``AiohttpDownloadHandler``.
* Fixed merging of multi-value response headers in ``NiquestsDownloadHandler``.
* Allowed importing ``HttpxDownloadHandler`` without ``h2`` installed.
* Improved wrapping of library-specific exceptions into Scrapy ones.
* CI improvements.

0.1.2 (2026-05-19)
------------------

This is the last version that supports Scrapy 2.15.x.

* Added support for Scrapy 2.16.x.
* Added ``py.typed``.
* Small improvements.
* CI improvements.

0.1.1 (2026-04-19)
------------------

* Fixed the README line that says which Scrapy versions are supported.
* CI improvements.
* Code cleanup.

0.1.0 (2026-04-19)
------------------

* Initial PyPI release.
