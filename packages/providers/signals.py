"""Live public demand / trend / news signals (free, keyless). All fail gracefully (ProviderUnavailable).

* GoogleTrendsRssProvider - India "Daily Search Trends" RSS. Real trending searches with Google's own
  approximate-traffic bucket ("500+", "2K+"). Kept only when relevant to trading/brokers/regulation.
* GoogleNewsRssProvider   - Google News RSS search (en-IN + hi-IN) per tracked broker and regulatory topic.
  Fresh coverage turns a broker into a news-led query ("<broker> news") for today's plan.
* measure_broker_demand   - per-broker demand index from autocomplete depth, category share and news volume.

None of these are search volumes. The trends bucket is Google's coarse public label; everything else is a
PROXY and is labelled as such in observations, scores and the UI.
"""

from __future__ import annotations

import math
import re
import time
import xml.etree.ElementTree as ET  # noqa: S405 - parsing Google's RSS over HTTPS, no DTD/entities expanded
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from packages.contracts.enums import Language, SourceType
from packages.contracts.flow import SearchObservation
from packages.domain.language import BROKERS, analyze_query
from packages.providers.base import ProviderUnavailable

USER_AGENT = "ATLAS-SEO-Research/0.1 (+https://github.com/NamanChordia07/seo-intelligence-engine; research demo)"
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
HT_NS = "{https://trends.google.com/trending/rss}"

# Domain lexicon for keeping a trending search: anything mentioning a broker, or one of these terms.
RELEVANT_TERMS = re.compile(
    r"\b(forex|fx|cfd|broker|trading|trader|currency|rupee|usd ?inr|dollar rate|rbi|sebi|fema|spread|leverage|"
    r"pip|mt4|mt5|metatrader|binary option|ed raid|फॉरेक्स|ट्रेडिंग|ब्रोकर|रुपया|आरबीआई|सेबी)\b",
    re.IGNORECASE,
)


def _get(url: str, params: dict[str, str] | None = None) -> str:
    try:
        resp = httpx.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError as exc:
        raise ProviderUnavailable(f"{url}: {exc}") from exc


def is_relevant(query: str) -> bool:
    return bool(RELEVANT_TERMS.search(query)) or bool(analyze_query(query).entity_keys)


def traffic_to_index(bucket: str | None) -> float | None:
    """'500+' / '2K+' / '1M+' -> 0-100 log-scaled index (100 ~ 1M+). Coarse by design."""
    if not bucket:
        return None
    m = re.match(r"([\d.,]+)\s*([KkMm]?)", bucket.strip())
    if not m:
        return None
    n = float(m.group(1).replace(",", "")) * {"": 1, "k": 1e3, "m": 1e6}[m.group(2).lower()]
    return round(max(0.0, min(100.0, (math.log10(max(n, 1)) - 1) * 20)), 1)  # 10->0, 100->20, 1K->40, 100K->80


# --------------------------------------------------------------------------- RSS parsing (pure, unit-tested)
@dataclass
class TrendItem:
    query: str
    traffic: str | None
    published: datetime | None
    news: list[dict[str, str]] = field(default_factory=list)


def parse_trends_rss(xml_text: str) -> list[TrendItem]:
    root = ET.fromstring(xml_text)  # noqa: S314
    out = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        pub = item.findtext("pubDate")
        news = [{"title": (n.findtext(f"{HT_NS}news_item_title") or "").strip(),
                 "url": (n.findtext(f"{HT_NS}news_item_url") or "").strip(),
                 "source": (n.findtext(f"{HT_NS}news_item_source") or "").strip()}
                for n in item.findall(f"{HT_NS}news_item")]
        out.append(TrendItem(query=title, traffic=item.findtext(f"{HT_NS}approx_traffic"),
                             published=parsedate_to_datetime(pub) if pub else None, news=news[:3]))
    return out


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: datetime | None


def parse_news_rss(xml_text: str) -> list[NewsItem]:
    root = ET.fromstring(xml_text)  # noqa: S314
    out = []
    for item in root.iter("item"):
        pub = item.findtext("pubDate")
        src = item.find("source")
        out.append(NewsItem(title=(item.findtext("title") or "").strip(), url=(item.findtext("link") or "").strip(),
                            source=(src.text or "").strip() if src is not None else "",
                            published=parsedate_to_datetime(pub) if pub else None))
    return out


# --------------------------------------------------------------------------- providers
class GoogleTrendsRssProvider:
    name = "google_trends_rss"
    URL = "https://trends.google.com/trending/rss"

    def rising(self, sim_day: int | None, languages: list[Language]) -> list[SearchObservation]:
        items = parse_trends_rss(_get(self.URL, {"geo": "IN"}))
        now = datetime.now(UTC)
        out = []
        for t in items:
            if not is_relevant(t.query):
                continue
            a = analyze_query(t.query)
            if a.language not in languages:
                continue
            out.append(SearchObservation(
                query=t.query[:300], language=a.language, locale=a.locale, source=self.name,
                source_type=SourceType.REAL_PUBLIC, confidence=0.7, observed_at=now,
                demand_proxy=traffic_to_index(t.traffic), trend_velocity=1.0, seed=None, entity_keys=a.entity_keys,
                is_news=bool(t.news), raw={"approx_traffic": t.traffic, "news": t.news,
                                           "note": "Google Trends India daily trending search; traffic is Google's coarse bucket"},
            ))
        return out


class GoogleNewsRssProvider:
    """Fresh coverage per broker/topic -> news-led queries. Records headlines so the brief can cite them."""

    name = "google_news_rss"
    URL = "https://news.google.com/rss/search"
    TOPICS = {Language.EN: ["forex trading india rbi", "rbi alert list forex"], Language.HI: ["फॉरेक्स ट्रेडिंग"]}

    def __init__(self, brokers: dict[str, str], window_days: int = 2, pause: float = 0.3):
        self.brokers = brokers
        self.window_days = window_days
        self.pause = pause
        self.headlines: dict[str, list[NewsItem]] = {}

    def _search(self, q: str, lang: Language) -> list[NewsItem]:
        params = ({"q": f"{q} when:{self.window_days}d", "hl": "hi", "gl": "IN", "ceid": "IN:hi"} if lang == Language.HI
                  else {"q": f"{q} when:{self.window_days}d", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
        items = parse_news_rss(_get(self.URL, params))
        time.sleep(self.pause)
        return items

    def rising(self, sim_day: int | None, languages: list[Language]) -> list[SearchObservation]:
        now = datetime.now(UTC)
        out: list[SearchObservation] = []
        for key, name in self.brokers.items():
            items = self._search(f'"{name}" forex', Language.EN)
            self.headlines[key] = items
            if items:
                out.append(self._obs(f"{name.lower()} news", Language.EN, items, now, [key]))
        for lang, topics in self.TOPICS.items():
            if lang not in languages:
                continue
            for topic in topics:
                items = self._search(topic, lang)
                self.headlines[topic] = items
                if items:
                    out.append(self._obs(topic, lang, items, now, analyze_query(topic).entity_keys))
        return out

    def _obs(self, q: str, lang: Language, items: list[NewsItem], now: datetime, entities: list[str]) -> SearchObservation:
        a = analyze_query(q)
        return SearchObservation(
            query=q, language=a.language if a.language in (Language.EN, Language.HI) else lang, locale=a.locale,
            source=self.name, source_type=SourceType.REAL_PUBLIC, confidence=0.6, observed_at=now,
            demand_proxy=None, trend_velocity=min(2.0, len(items) / 10), seed=None, entity_keys=entities or a.entity_keys,
            is_news=True, raw={"articles_in_window": len(items), "window_days": self.window_days,
                               "headlines": [{"title": i.title[:200], "url": i.url, "source": i.source} for i in items[:5]],
                               "note": "Article count is a coverage proxy, not search volume"},
        )


# --------------------------------------------------------------------------- broker demand
CATEGORY_SEEDS = ["forex broker", "best forex broker in india", "forex trading app", "forex broker india",
                  "forex trading app india", "best trading app for forex"]


def autocomplete(q: str, hl: str = "en") -> list[str]:
    text = _get("https://suggestqueries.google.com/complete/search", {"client": "firefox", "hl": hl, "gl": "in", "q": q})
    try:
        import json

        data = json.loads(text)
    except ValueError as exc:
        raise ProviderUnavailable(f"autocomplete returned non-JSON: {exc}") from exc
    return [s for s in (data[1] if isinstance(data, list) and len(data) > 1 else []) if isinstance(s, str)]


def brokers_in(text: str) -> list[str]:
    padded = f" {text.lower()} "
    return [k for k, aliases in BROKERS.items() if any(f" {a} " in padded or (len(a) > 4 and a in padded) for a in aliases)]


@dataclass
class BrokerDemand:
    entity_key: str
    name: str
    index: float
    components: dict[str, Any]
    tracked: bool
    source_type: str


def demand_index(suggestion_depth: int, india_suggestions: int, category_hits: float, news_7d: int) -> float:
    """0-100 PROXY. Weights favour Indian-market autocomplete presence over news coverage."""
    depth = min(suggestion_depth, 10) / 10 * 100
    india = min(india_suggestions, 3) / 3 * 100
    category = min(category_hits, 3) / 3 * 100
    news = min(math.log10(news_7d + 1) / 2, 1) * 100  # 99 articles -> 100
    return round(0.35 * depth + 0.15 * india + 0.30 * category + 0.20 * news, 1)


INDIA_HINTS = re.compile(r"\b(india|indian|inr|upi|hindi|legal in india|rupee)\b|हिंदी|भारत", re.IGNORECASE)


def measure_broker_demand(tracked: dict[str, str], pause: float = 0.25) -> tuple[list[BrokerDemand], list[str]]:
    """Live: autocomplete depth per broker + category share across generic seeds + 7-day news count.

    Also surfaces untracked lexicon brokers that appear in category autocompletes (discovery)."""
    from packages.domain.language import BROKER_NAMES

    failures: list[str] = []
    category: dict[str, float] = {}
    for seed in CATEGORY_SEEDS:
        try:
            for pos, s in enumerate(autocomplete(seed)):
                for k in brokers_in(s):
                    category[k] = category.get(k, 0) + 1 / (1 + pos * 0.25)
        except ProviderUnavailable as exc:
            failures.append(f"autocomplete '{seed}': {exc}")
        time.sleep(pause)
    keys = list(dict.fromkeys([*tracked, *category]))
    out = []
    for key in keys:
        name = tracked.get(key) or BROKER_NAMES.get(key, key)
        sugg: list[str] = []
        news: list[NewsItem] = []
        try:
            sugg = autocomplete(f"{name.lower()} ")
        except ProviderUnavailable as exc:
            failures.append(f"autocomplete '{name}': {exc}")
        time.sleep(pause)
        try:
            news = parse_news_rss(_get(GoogleNewsRssProvider.URL, {"q": f'"{name}" forex when:7d', "hl": "en-IN", "gl": "IN",
                                                                   "ceid": "IN:en"}))
        except (ProviderUnavailable, ET.ParseError) as exc:
            failures.append(f"news '{name}': {exc}")
        time.sleep(pause)
        india = [s for s in sugg if INDIA_HINTS.search(s)]
        comps = {"autocomplete_depth": len(sugg), "india_suggestions": len(india), "category_share": round(category.get(key, 0), 2),
                 "news_7d": len(news), "sample_suggestions": sugg[:6], "sample_headlines": [n.title[:140] for n in news[:3]]}
        out.append(BrokerDemand(key, name, demand_index(len(sugg), len(india), category.get(key, 0), len(news)), comps,
                                key in tracked, SourceType.PROXY.value))
    out.sort(key=lambda b: -b.index)
    return out, failures


def simulated_broker_demand(tracked: dict[str, str], observations: list[dict[str, Any]], date: str) -> list[BrokerDemand]:
    """Demo mode: aggregate the day fixture's SIMULATED demand per broker (labelled SIMULATED)."""
    agg: dict[str, dict[str, float]] = {}
    for row in observations:
        for k in analyze_query(row["q"]).entity_keys:
            a = agg.setdefault(k, {"queries": 0, "demand_sum": 0.0, "trend_max": -1.0, "news": 0})
            a["queries"] += 1
            a["demand_sum"] += float(row["demand"])
            a["trend_max"] = max(a["trend_max"], float(row["trend"]))
            a["news"] += 1 if row.get("news") else 0
    from packages.domain.language import BROKER_NAMES

    out = []
    for key in dict.fromkeys([*tracked, *agg]):
        a = agg.get(key, {"queries": 0, "demand_sum": 0.0, "trend_max": 0.0, "news": 0})
        idx = round(min(100.0, a["demand_sum"] / 4), 1)
        out.append(BrokerDemand(key, tracked.get(key) or BROKER_NAMES.get(key, key), idx,
                                {"queries_observed": a["queries"], "demand_sum": a["demand_sum"], "trend_max": a["trend_max"],
                                 "news_queries": a["news"], "fixture_date": date},
                                key in tracked, SourceType.SIMULATED.value))
    out.sort(key=lambda b: -b.index)
    return out

