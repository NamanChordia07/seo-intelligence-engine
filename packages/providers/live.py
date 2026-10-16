"""Optional live public providers. All of them fail gracefully (ProviderUnavailable).

* GoogleAutocompleteProvider - public suggest endpoint; returns query *presence* only
  (REAL_PUBLIC observation, no volume). Low request budget, short timeouts.
* SearxngSerpProvider        - self-hosted SearXNG JSON API for SERP observations.
* SafeHttpExtractor          - httpx page fetcher with SSRF guard, robots.txt, size/time limits.
* Crawl4AIExtractor          - used when the optional `crawl4ai` extra is installed.
"""

from __future__ import annotations

import ipaddress
import re
import socket
import time
from datetime import UTC, datetime
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from packages.contracts.enums import Language, SourceType
from packages.contracts.flow import SearchObservation, SerpResult, SerpSnapshot
from packages.domain.discovery import SeedQuery
from packages.domain.language import analyze_query
from packages.providers.base import ExtractedPage, ProviderUnavailable

USER_AGENT = "ATLAS-SEO-Research/0.1 (+demo; respectful crawler)"
MAX_BYTES = 2_000_000
TIMEOUT = httpx.Timeout(8.0, connect=4.0)


# --------------------------------------------------------------------------- URL safety
def assert_public_url(url: str) -> None:
    """SSRF guard: only http(s) to public, non-internal addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ProviderUnavailable(f"unsupported URL scheme: {url}")
    host = parsed.hostname
    if host in ("localhost",) or host.endswith((".local", ".internal", ".example")):
        raise ProviderUnavailable(f"refusing non-public host: {host}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ProviderUnavailable(f"DNS failure for {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ProviderUnavailable(f"refusing private address {ip} for {host}")


def robots_allows(url: str, client: httpx.Client) -> bool:
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = client.get(robots_url, timeout=TIMEOUT)
    except httpx.HTTPError:
        return True  # unreachable robots.txt -> standard practice is to allow
    if resp.status_code >= 400:
        return True
    rp = RobotFileParser()
    rp.parse(resp.text.splitlines())
    return rp.can_fetch(USER_AGENT, url)


# --------------------------------------------------------------------------- suggestions
class GoogleAutocompleteProvider:
    name = "google_autocomplete"
    ENDPOINT = "https://suggestqueries.google.com/complete/search"

    def __init__(self, budget: int = 12, pause: float = 0.25):
        self.budget = budget
        self.pause = pause

    def suggest(self, seed: SeedQuery, sim_day: int | None) -> list[SearchObservation]:
        if self.budget <= 0:
            return []
        self.budget -= 1
        hl = "hi" if seed.language == Language.HI else "en"
        try:
            resp = httpx.get(
                self.ENDPOINT, params={"client": "firefox", "hl": hl, "gl": "in", "q": seed.query},
                headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable(f"autocomplete unavailable: {exc}") from exc
        now = datetime.now(UTC)
        out = []
        for pos, s in enumerate((data[1] if isinstance(data, list) and len(data) > 1 else [])[:8]):
            a = analyze_query(s)
            out.append(SearchObservation(
                query=s[:300], language=a.language, locale=a.locale, source=self.name,
                source_type=SourceType.REAL_PUBLIC, confidence=0.5, observed_at=now, demand_proxy=position_proxy(pos),
                trend_velocity=None, seed=seed.query, entity_keys=a.entity_keys,
                raw={"note": "Presence in public autocomplete; no volume data", "position": pos + 1,
                     "demand_proxy_basis": "autocomplete rank (PROXY)"},
            ))
        if self.pause:
            time.sleep(self.pause)
        return out


def position_proxy(position: int) -> float:
    """Autocomplete rank -> weak relative demand PROXY (rank 1 = 70, rank 8 = 35). Never a volume."""
    return float(max(35, 70 - 5 * position))


# --------------------------------------------------------------------------- SERP
class SearxngSerpProvider:
    name = "searxng"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def serp(self, query: str, language: Language, intent_key: str) -> SerpSnapshot:
        try:
            resp = httpx.get(
                f"{self.base_url}/search",
                params={"q": query, "format": "json", "language": "hi-IN" if language == Language.HI else "en-IN"},
                headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailable(f"SearXNG unavailable: {exc}") from exc
        results = []
        for i, r in enumerate(data.get("results", [])[:10], start=1):
            url = r.get("url", "")
            results.append(SerpResult(
                position=i, url=url, title=r.get("title", "")[:300], domain=urlparse(url).netloc,
                snippet=(r.get("content") or "")[:500], published=(r.get("publishedDate") or "")[:7] or None,
            ))
        return SerpSnapshot(query=query, language=language, captured_at=datetime.now(UTC), source=self.name,
                            source_type=SourceType.REAL_PUBLIC, results=results)


# --------------------------------------------------------------------------- extraction
TAG_RE = re.compile(r"<[^>]+>")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
H_RE = re.compile(r"<h[1-3][^>]*>(.*?)</h[1-3]>", re.IGNORECASE | re.DOTALL)
SCRIPT_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


class SafeHttpExtractor:
    name = "httpx_extractor"

    def extract(self, url: str) -> ExtractedPage:
        assert_public_url(url)
        with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=TIMEOUT) as client:
            if not robots_allows(url, client):
                return ExtractedPage(url=url, status=0, error="disallowed by robots.txt")
            try:
                with client.stream("GET", url) as resp:
                    final = str(resp.url)
                    if final != url:
                        assert_public_url(final)
                    chunks, size = [], 0
                    for chunk in resp.iter_bytes():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            break
                        chunks.append(chunk)
                    status = resp.status_code
                    ctype = resp.headers.get("content-type", "")
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(f"fetch failed: {exc}") from exc
        if "html" not in ctype:
            return ExtractedPage(url=url, status=status, error=f"non-HTML content ({ctype or 'unknown'})")
        html = b"".join(chunks).decode("utf-8", errors="replace")
        html = SCRIPT_RE.sub(" ", html)
        title = TAG_RE.sub("", (TITLE_RE.search(html).group(1) if TITLE_RE.search(html) else "")).strip()
        heads = [" ".join(TAG_RE.sub("", h).split()) for h in H_RE.findall(html)][:30]
        text = " ".join(TAG_RE.sub(" ", html).split())
        return ExtractedPage(url=url, status=status, title=title[:300], headings=heads, text=text[:20000],
                             word_count=len(text.split()))


class Crawl4AIExtractor:
    """Uses Crawl4AI (optional extra) for JS-heavy pages; falls back to SafeHttpExtractor."""

    name = "crawl4ai"

    def extract(self, url: str) -> ExtractedPage:
        assert_public_url(url)
        try:
            import asyncio

            from crawl4ai import AsyncWebCrawler  # type: ignore[import-not-found]
        except ImportError:
            return SafeHttpExtractor().extract(url)

        async def _run() -> ExtractedPage:
            async with AsyncWebCrawler() as crawler:
                res = await crawler.arun(url=url)
                md = getattr(res, "markdown", "") or ""
                return ExtractedPage(url=url, status=getattr(res, "status_code", 200) or 200,
                                     title=(getattr(res, "metadata", {}) or {}).get("title", ""),
                                     text=str(md)[:20000], word_count=len(str(md).split()))

        try:
            return asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001 - crawler failures must degrade gracefully
            raise ProviderUnavailable(f"crawl4ai failed: {exc}") from exc
