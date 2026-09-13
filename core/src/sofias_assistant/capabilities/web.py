"""Replaceable search and bounded, SSRF-aware HTTP read capabilities."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol
from urllib.error import HTTPError
from urllib.parse import quote_plus, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sofias_assistant.execution.models import ToolSpec


class WebSearchBackend(Protocol):
    async def search(
        self, query: str, *, max_results: int
    ) -> tuple[dict[str, str], ...]: ...


@dataclass(frozen=True, slots=True)
class FakeSearchBackend:
    """Deterministic offline backend for correctness and CI."""

    results: tuple[dict[str, str], ...] = (
        {
            "title": "Sofia fixture",
            "url": "https://example.test/sofia",
            "snippet": "deterministic search result",
        },
    )

    async def search(
        self, query: str, *, max_results: int
    ) -> tuple[dict[str, str], ...]:
        if not query.strip():
            raise ValueError("query must not be blank")
        return tuple({**item, "query": query} for item in self.results[:max_results])


class _SearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        href = values.get("href")
        if tag == "a" and href and "result__a" in (values.get("class") or ""):
            self._current = {"url": href}
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current is not None:
            self._current["title"] = " ".join("".join(self._text).split())
            self._current["snippet"] = ""
            self.results.append(self._current)
            self._current = None


class DuckDuckGoSearchBackend:
    """Small real backend; provider-native HTML never crosses the Tool boundary."""

    async def search(
        self, query: str, *, max_results: int
    ) -> tuple[dict[str, str], ...]:
        url = "https://html.duckduckgo.com/html/?q=" + quote_plus(query)
        body, _ = await asyncio.to_thread(_fetch_once, url, 512 * 1024, 10.0, False)
        parser = _SearchParser()
        parser.feed(body.decode("utf-8", errors="replace"))
        return tuple(parser.results[:max_results])


class WebReader:
    """HTTP/HTTPS reader with DNS/IP checks, bounded redirects and response size."""

    def __init__(
        self,
        *,
        search_backend: WebSearchBackend | None = None,
        max_response_bytes: int = 2 * 1024 * 1024,
        max_text_chars: int = 1_000_000,
        max_redirects: int = 3,
        allow_loopback: bool = False,
    ) -> None:
        self.search_backend = search_backend or DuckDuckGoSearchBackend()
        self.max_response_bytes = max_response_bytes
        self.max_text_chars = max_text_chars
        self.max_redirects = max_redirects
        self.allow_loopback = allow_loopback

    def specs(self) -> tuple[ToolSpec, ...]:
        return (
            ToolSpec(
                name="web.search",
                version="1",
                description="Search through a replaceable bounded backend",
                capability="web.search",
                handler=self.search,
                resource_resolver=lambda args: (
                    "web.search:" + str(args["query"]).strip()
                ),
                input_validator=self._validate_search,
            ),
            ToolSpec(
                name="web.read",
                version="1",
                description="Read bounded text from an HTTP or HTTPS URL",
                capability="web.read",
                handler=self.read,
                resource_resolver=lambda args: validate_url(
                    args["url"], allow_loopback=self.allow_loopback
                ),
                input_validator=self._validate_read,
            ),
        )

    def _validate_search(self, arguments: Mapping[str, object]) -> Mapping[str, object]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 512:
            raise ValueError("query is invalid")
        maximum = arguments.get("max_results", 10)
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 0 < maximum <= 20
        ):
            raise ValueError("max_results is invalid")
        return {"query": query.strip(), "max_results": maximum}

    def _validate_read(self, arguments: Mapping[str, object]) -> Mapping[str, object]:
        url = validate_url(arguments.get("url"), allow_loopback=self.allow_loopback)
        return {"url": url}

    async def search(self, arguments: Mapping[str, object]) -> dict[str, object]:
        maximum = arguments["max_results"]
        if not isinstance(maximum, int):
            raise ValueError("max_results is invalid")
        results = await self.search_backend.search(
            str(arguments["query"]), max_results=maximum
        )
        return {"query": str(arguments["query"]), "results": results}

    async def read(self, arguments: Mapping[str, object]) -> dict[str, object]:
        current = validate_url(arguments["url"], allow_loopback=self.allow_loopback)
        for redirect_count in range(self.max_redirects + 1):
            try:
                body, response_url = await asyncio.to_thread(
                    _fetch_once,
                    current,
                    self.max_response_bytes,
                    10.0,
                    self.allow_loopback,
                )
            except _Redirected as redirect:
                if redirect_count >= self.max_redirects:
                    raise ValueError("redirect limit exceeded") from redirect
                current = validate_url(
                    redirect.location, allow_loopback=self.allow_loopback
                )
                continue
            current = validate_url(response_url, allow_loopback=self.allow_loopback)
            return {
                "url": current,
                "text": body.decode("utf-8", errors="replace")[: self.max_text_chars],
                "bytes": len(body),
                "redirects": redirect_count,
            }
        raise ValueError("redirect limit exceeded")


def validate_url(value: object, *, allow_loopback: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("url must be a non-empty string")
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only HTTP and HTTPS URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("URL credentials are not supported")
    host = parsed.hostname.rstrip(".").casefold()
    if host in {"metadata.google.internal", "metadata", "instance-data"}:
        raise ValueError("metadata endpoints are not allowed")
    addresses = _resolve_addresses(host)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not allow_loopback and (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_unspecified
            or ip.is_reserved
            or ip.is_multicast
        ):
            raise ValueError("private or local network destinations are not allowed")
    return parsed.geturl()


def _resolve_addresses(host: str) -> tuple[str, ...]:
    try:
        return (str(ipaddress.ip_address(host)),)
    except ValueError:
        try:
            return tuple(
                sorted(
                    {
                        str(item[4][0])
                        for item in socket.getaddrinfo(
                            host, None, type=socket.SOCK_STREAM
                        )
                    }
                )
            )
        except OSError as error:
            raise ValueError("URL host could not be resolved") from error


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


class _Redirected(Exception):
    def __init__(self, location: str) -> None:
        self.location = location


def _fetch_once(
    url: str, max_bytes: int, timeout: float, allow_loopback: bool
) -> tuple[bytes, str]:
    opener = build_opener(_NoRedirectHandler())
    request = Request(url, headers={"User-Agent": "SofiasAssistant/0.1"})
    try:
        response = opener.open(request, timeout=timeout)
    except HTTPError as error:
        if error.code not in {301, 302, 303, 307, 308}:
            raise ValueError("web request failed") from error
        location = error.headers.get("Location")
        if not location:
            raise ValueError("redirect has no destination") from error
        raise _Redirected(urljoin(url, location))
    try:
        content_type = response.headers.get_content_type()
        if not (
            content_type.startswith("text/")
            or content_type in {"application/json", "application/xml"}
        ):
            raise ValueError("response content type is not readable text")
        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ValueError("response exceeds the bounded size")
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("response exceeds the bounded size")
        return data, response.geturl()
    finally:
        response.close()
