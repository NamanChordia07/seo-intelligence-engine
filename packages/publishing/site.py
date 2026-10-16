"""Static site builder: approved articles -> publish-ready, zero-JS HTML for Indian mobile networks.

Pure function of its inputs (no DB / no I/O): `build_site(pages, project)` returns {path: bytes} + a report.

Publication gate (the compliance decision stays authoritative):
* APPROVED + ELIGIBLE_*         -> /<locale>/guides/<slug>/  index,follow, in sitemap
* IN_REVIEW / REQUIRES_REVIEW   -> /_preview/...             noindex,nofollow, banner, never in sitemap
* BLOCK / BLOCKED_* / red-team  -> not exported at all
Platform CTA: rendered only when the project's India authorization is VERIFIED; otherwise withheld and reported.

Performance model: one HTML document per page, CSS inlined, no web fonts (system Devanagari fonts on Android),
no JavaScript, no images. Load time is *estimated* with Lighthouse's mobile "Slow 4G" throttling profile.
"""

from __future__ import annotations

import gzip
import html
import json
import re
from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin

from packages.domain.seo import SITE_SECTIONS, article_path

# Lighthouse mobile simulated throttling ("Slow 4G"): 150 ms RTT, 1.6 Mbps down.
SLOW_4G_RTT_MS = 150
SLOW_4G_KBPS = 1638.4
FIRST_FLIGHT_BYTES = 14_600  # ~10 TCP segments: fits in the first round trip after the handshake
PAGE_BUDGET_GZ = 50_000

LOCALE_LABEL = {"en-in": "English (India)", "hi-in": "हिन्दी (भारत)"}
HTML_LANG = {"en": "en-IN", "hi": "hi-IN", "hi-Latn": "hi-Latn"}

UI = {
    "en": {"home": "Home", "guides": "Guides", "updated": "Last reviewed", "preview": "PREVIEW - pending compliance review. Not indexed, not for publication.",
           "cta_title": "Continue on {name}", "cta_body": "Open the platform to compare instruments and costs. Trading involves risk of loss.",
           "cta_button": "Visit {name}"},
    "hi": {"home": "होम", "guides": "गाइड", "updated": "अंतिम समीक्षा", "preview": "प्रीव्यू - अनुपालन समीक्षा लंबित। इंडेक्स नहीं, प्रकाशन के लिए नहीं।",
           "cta_title": "{name} पर आगे बढ़ें", "cta_body": "इंस्ट्रूमेंट और लागत की तुलना के लिए प्लेटफ़ॉर्म खोलें। ट्रेडिंग में नुकसान का जोखिम है।",
           "cta_button": "{name} पर जाएँ"},
}

CSS = """
:root{--fg:#1a1d21;--muted:#5b6470;--bg:#fff;--line:#e3e6ea;--accent:#0b6b4f;--warn-bg:#fff6e0;--warn:#7a5200;--soft:#f5f7f9}
@media (prefers-color-scheme:dark){:root{--fg:#e7eaee;--muted:#9aa3ad;--bg:#111417;--line:#2a2f35;--accent:#4cc79a;--warn-bg:#2b2410;--warn:#f0c66b;--soft:#1a1e22}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:17px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans","Noto Sans Devanagari","Nirmala UI",Mangal,sans-serif}
header,main,footer{max-width:44rem;margin:0 auto;padding:0 16px}
header{display:flex;justify-content:space-between;align-items:center;gap:12px;padding-top:14px;padding-bottom:14px;border-bottom:1px solid var(--line);font-size:15px}
header a{color:var(--fg);text-decoration:none;font-weight:600}nav a{margin-left:14px;color:var(--muted);font-weight:500}
.crumbs{font-size:14px;color:var(--muted);margin:18px 0 0}.crumbs a{color:var(--muted)}
h1{font-size:1.75rem;line-height:1.25;margin:.5rem 0 1rem}h2{font-size:1.3rem;line-height:1.3;margin:2.2rem 0 .6rem}h3{font-size:1.08rem;margin:1.6rem 0 .4rem}
a{color:var(--accent);text-underline-offset:2px}p,li{overflow-wrap:anywhere}
blockquote{margin:1.2rem 0;padding:.8rem 1rem;background:var(--warn-bg);color:var(--fg);border-left:4px solid var(--warn);border-radius:6px}
blockquote p{margin:.2rem 0}
.tbl{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:1rem 0;border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;min-width:100%;font-size:15px}th,td{padding:.55rem .7rem;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--soft)}th:first-child,td:first-child{position:sticky;left:0;background:var(--soft);font-weight:600}
code{font-size:.85em;background:var(--soft);padding:.1em .35em;border-radius:4px}
.footnotes{font-size:14px;color:var(--muted)}.footnotes ol{padding-left:1.2rem}hr{border:0;border-top:1px solid var(--line);margin:2rem 0}
.meta{font-size:14px;color:var(--muted)}.preview{background:var(--warn-bg);color:var(--warn);font-weight:600;padding:.7rem 16px;text-align:center;font-size:14px}
.cta{margin:2rem 0;padding:1.1rem;border:1px solid var(--line);border-radius:10px;background:var(--soft)}
.cta a{display:inline-block;margin-top:.5rem;padding:.75rem 1.1rem;min-height:48px;border-radius:8px;background:var(--accent);color:#fff;text-decoration:none;font-weight:600}
ul.cards{list-style:none;padding:0}ul.cards li{padding:.9rem 0;border-bottom:1px solid var(--line)}ul.cards small{display:block;color:var(--muted)}
footer{margin-top:3rem;padding-top:1rem;padding-bottom:2rem;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}
"""
CSS = re.sub(r"\s*\n\s*", "", CSS)

FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
INTERNAL_HREF_RE = re.compile(r'href="/(en-in|hi-in)/')


@dataclass
class PageInput:
    article_id: str
    slug: str
    language: str  # en | hi | hi-Latn
    title: str
    meta_description: str
    markdown: str
    status: str  # APPROVED | IN_REVIEW | BLOCKED | PUBLISHED(inventory)
    compliance_status: str
    eligibility: str
    content_class: str
    origin: str  # GENERATED | INVENTORY
    intent_key: str
    updated: str  # ISO date
    seo: dict[str, Any] = field(default_factory=dict)
    is_test_fixture: bool = False


@dataclass
class ProjectInput:
    domain: str
    site_name: str
    authorization: str  # UNKNOWN | VERIFIED | NOT_AUTHORIZED
    platform_name: str
    platform_url: str | None = None


def gate(p: PageInput) -> tuple[str, str]:
    """-> (decision, reason). decision: PUBLISH | PREVIEW | EXCLUDE."""
    if p.is_test_fixture:
        return "EXCLUDE", "red-team fixture"
    if p.origin == "INVENTORY":
        return "PUBLISH", "pre-existing site page"
    if p.compliance_status == "BLOCK" or p.eligibility.startswith("BLOCKED") or p.status == "BLOCKED":
        return "EXCLUDE", f"compliance {p.compliance_status} / {p.eligibility}"
    if p.status == "APPROVED" and p.eligibility.startswith("ELIGIBLE"):
        return "PUBLISH", f"{p.compliance_status}, {p.eligibility}"
    return "PREVIEW", f"awaiting human review ({p.compliance_status})"


def section(language: str) -> str:
    return SITE_SECTIONS.get(language, "en-in")


def _md() -> MarkdownIt:
    # html=False: raw HTML in model output is escaped, never rendered (no script/iframe injection).
    return MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False}).enable("table").use(footnote_plugin)


def render_body(markdown: str, base: str) -> tuple[str, str]:
    """-> (h1 text, body html without the H1). Internal absolute links get the deployment base prefix."""
    body = FRONTMATTER_RE.sub("", markdown, count=1).lstrip()
    h1 = ""
    m = re.match(r"# (.+)\n", body)
    if m:
        h1, body = m.group(1).strip(), body[m.end():]
    out = _md().render(body)
    out = out.replace("<table>", '<div class="tbl"><table>').replace("</table>", "</table></div>")
    if base:
        out = INTERNAL_HREF_RE.sub(lambda mm: f'href="{base}/{mm.group(1)}/', out)
    return h1, out


def estimate(html_bytes: bytes) -> dict[str, Any]:
    gz = len(gzip.compress(html_bytes, 9))
    # DNS + TCP + TLS 1.3 (~3 RTT) + request (1 RTT) + transfer at Slow 4G bandwidth; one document, no subresources.
    transfer_ms = gz * 8 / (SLOW_4G_KBPS * 1000) * 1000
    est = 4 * SLOW_4G_RTT_MS + transfer_ms
    return {"html_bytes": len(html_bytes), "gzip_bytes": gz, "requests": 1, "js_bytes": 0, "font_requests": 0,
            "first_flight": gz <= FIRST_FLIGHT_BYTES, "est_load_ms_slow4g": round(est),
            "budget_ok": gz <= PAGE_BUDGET_GZ}


def _jsonld(obj: dict[str, Any]) -> str:
    return '<script type="application/ld+json">' + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/") + "</script>"


def _shell(*, lang: str, title: str, description: str, canonical: str, robots: str, alternates: list[dict[str, str]],
           jsonld: list[dict[str, Any]], body: str, base: str, project: ProjectInput, banner: str = "") -> bytes:
    e = html.escape
    alt = "".join(f'<link rel="alternate" hreflang="{e(a["hreflang"])}" href="{e(a["href"])}">' for a in alternates)
    doc = (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{e(title)}</title><meta name=\"description\" content=\"{e(description)}\">"
        f'<meta name="robots" content="{robots}"><link rel="canonical" href="{e(canonical)}">{alt}'
        f'<meta property="og:type" content="article"><meta property="og:title" content="{e(title)}">'
        f'<meta property="og:description" content="{e(description)}"><meta property="og:url" content="{e(canonical)}">'
        f'<meta name="theme-color" content="#0b6b4f"><style>{CSS}</style>{"".join(_jsonld(j) for j in jsonld)}</head><body>'
        f"{banner}<header><a href=\"{base}/\">{e(project.site_name)}</a><nav>"
        f'<a href="{base}/en-in/guides/" hreflang="en-IN">English</a><a href="{base}/hi-in/guides/" hreflang="hi-IN">हिन्दी</a></nav></header>'
        f"<main>{body}</main><footer>Educational content. Trading forex/CFDs involves a high risk of losing money. "
        f"Nothing here is investment advice. In India, residents may trade forex only through RBI-authorised entities on "
        f"authorised platforms or recognised exchanges.</footer></body></html>"
    )
    return doc.encode("utf-8")


def _cta(p: PageInput, project: ProjectInput) -> tuple[str, str]:
    """Platform CTA only when authorization is VERIFIED and a URL is configured; returns (html, reason)."""
    if project.authorization != "VERIFIED":
        return "", f"withheld: India authorization {project.authorization}"
    if not project.platform_url:
        return "", "withheld: no platform URL configured"
    t = UI["hi" if p.language == "hi" else "en"]
    e = html.escape
    return (f'<aside class="cta"><strong>{e(t["cta_title"].format(name=project.platform_name))}</strong>'
            f'<p>{e(t["cta_body"])}</p><a href="{e(project.platform_url)}">{e(t["cta_button"].format(name=project.platform_name))}</a></aside>',
            "rendered: authorization VERIFIED")


def build_site(pages: list[PageInput], project: ProjectInput, base: str = "") -> tuple[dict[str, bytes], dict[str, Any]]:
    base = base.rstrip("/")
    files: dict[str, bytes] = {}
    report_pages: list[dict[str, Any]] = []
    published: list[PageInput] = []
    for p in pages:
        decision, reason = gate(p)
        entry: dict[str, Any] = {"article_id": p.article_id, "slug": p.slug, "title": p.title, "language": p.language,
                                 "origin": p.origin, "decision": decision, "reason": reason, "compliance_status": p.compliance_status}
        if decision == "EXCLUDE":
            report_pages.append(entry)
            continue
        sec = section(p.language)
        canonical = p.seo.get("canonical") or f"https://{project.domain}{article_path(p.language, p.slug)}"
        alternates = p.seo.get("hreflang") or [{"hreflang": HTML_LANG.get(p.language, "en-IN"), "href": canonical},
                                                {"hreflang": "x-default", "href": canonical}]
        prefix = "_preview/" if decision == "PREVIEW" else ""
        h1, body_html = render_body(p.markdown, base)
        t = UI["hi" if p.language == "hi" else "en"]
        cta_html, cta_reason = _cta(p, project)
        crumbs = (f'<p class="crumbs"><a href="{base}/">{t["home"]}</a> › <a href="{base}/{sec}/guides/">{t["guides"]}</a></p>')
        article = (f"{crumbs}<article><h1>{html.escape(h1 or p.title)}</h1>"
                   f'<p class="meta">{t["updated"]}: <time datetime="{p.updated}">{p.updated}</time></p>{body_html}{cta_html}</article>')
        ld = p.seo.get("json_ld") or {}
        jsonld = [ld[k] for k in ("article", "faq", "breadcrumb") if ld.get(k)]
        if ld.get("faq") and not ld["faq"].get("mainEntity"):
            jsonld = [j for j in jsonld if j is not ld["faq"]]
        banner = f'<div class="preview" role="status">{html.escape(t["preview"])}</div>' if decision == "PREVIEW" else ""
        doc = _shell(lang=HTML_LANG.get(p.language, "en-IN"), title=p.title, description=p.meta_description, canonical=canonical,
                     robots="noindex,nofollow" if decision == "PREVIEW" else "index,follow,max-snippet:-1",
                     alternates=alternates, jsonld=jsonld, body=article, base=base, project=project, banner=banner)
        path = f"{prefix}{sec}/guides/{p.slug}/index.html"
        files[path] = doc
        entry.update(path="/" + path.removesuffix("index.html"), canonical=canonical, cta=cta_reason,
                     hreflang=[a["hreflang"] for a in alternates], schema=[j.get("@type") for j in jsonld], **estimate(doc))
        report_pages.append(entry)
        if decision == "PUBLISH":
            published.append(p)

    # hub pages per locale + root
    for sec, label in LOCALE_LABEL.items():
        items = [p for p in published if section(p.language) == sec]
        lis = "".join(f'<li><a href="{base}/{sec}/guides/{p.slug}/">{html.escape(p.title)}</a>'
                      f"<small>{html.escape(p.meta_description[:150])}</small></li>" for p in items)
        lang = "hi-IN" if sec == "hi-in" else "en-IN"
        files[f"{sec}/guides/index.html"] = _shell(
            lang=lang, title=f"{label} - {project.site_name}", description=f"{project.site_name}: {label} guides",
            canonical=f"https://{project.domain}/{sec}/guides/", robots="index,follow",
            alternates=[{"hreflang": "en-IN", "href": f"https://{project.domain}/en-in/guides/"},
                        {"hreflang": "hi-IN", "href": f"https://{project.domain}/hi-in/guides/"},
                        {"hreflang": "x-default", "href": f"https://{project.domain}/en-in/guides/"}],
            jsonld=[], body=f"<h1>{html.escape(label)}</h1><ul class=\"cards\">{lis or '<li>No published guides yet.</li>'}</ul>",
            base=base, project=project)
    files["index.html"] = _shell(
        lang="en-IN", title=project.site_name, description=f"{project.site_name} - trading education for India in English and Hindi",
        canonical=f"https://{project.domain}/", robots="index,follow", alternates=[], jsonld=[
            {"@context": "https://schema.org", "@type": "WebSite", "name": project.site_name, "url": f"https://{project.domain}/",
             "inLanguage": ["en-IN", "hi-IN"]}],
        body=f'<h1>{html.escape(project.site_name)}</h1><ul class="cards">'
             f'<li><a href="{base}/en-in/guides/">English guides</a><small>{len([p for p in published if section(p.language) == "en-in"])} pages</small></li>'
             f'<li><a href="{base}/hi-in/guides/">हिन्दी गाइड</a><small>{len([p for p in published if section(p.language) == "hi-in"])} पेज</small></li></ul>',
        base=base, project=project)
    files["sitemap.xml"] = sitemap(published, project).encode("utf-8")
    files["robots.txt"] = (f"User-agent: *\nAllow: /\nDisallow: /_preview/\n\nSitemap: https://{project.domain}/sitemap.xml\n").encode()

    built = [r for r in report_pages if r["decision"] != "EXCLUDE"]
    report = {
        "domain": project.domain, "base": base or "/", "authorization": project.authorization,
        "counts": {d: len([r for r in report_pages if r["decision"] == d]) for d in ("PUBLISH", "PREVIEW", "EXCLUDE")},
        "performance": {
            "profile": f"Lighthouse mobile 'Slow 4G' (RTT {SLOW_4G_RTT_MS} ms, {SLOW_4G_KBPS:.0f} kbps) - estimate, not a field measurement",
            "max_gzip_bytes": max((r["gzip_bytes"] for r in built), default=0),
            "max_est_load_ms": max((r["est_load_ms_slow4g"] for r in built), default=0),
            "all_within_budget": all(r["budget_ok"] for r in built),
            "budget_gzip_bytes": PAGE_BUDGET_GZ,
        },
        "pages": report_pages,
        "files": sorted(files),
    }
    return files, report


def sitemap(pages: list[PageInput], project: ProjectInput) -> str:
    """URL set with xhtml:link hreflang alternates (indexable pages only)."""
    rows = []
    for p in pages:
        loc = p.seo.get("canonical") or f"https://{project.domain}{article_path(p.language, p.slug)}"
        alts = "".join(f'<xhtml:link rel="alternate" hreflang="{html.escape(a["hreflang"])}" href="{html.escape(a["href"])}"/>'
                       for a in (p.seo.get("hreflang") or []))
        rows.append(f"<url><loc>{html.escape(loc)}</loc><lastmod>{p.updated}</lastmod>{alts}</url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:xhtml="http://www.w3.org/1999/xhtml">' + "".join(rows) + "</urlset>\n")
