"""LLM provider abstraction.

* DemoLLMProvider             - deterministic drafting from the curated content library
                                (zero cost, zero network; default for the walkthrough)
* OpenAICompatibleLLMProvider - any OpenAI-compatible endpoint: local Ollama
                                (http://127.0.0.1:11434/v1) or an optional hosted API.

Every model response is parsed as JSON and validated against ``LLMArticlePayload``;
invalid output is retried with the validation error fed back, then surfaced as
``LLMOutputError`` so the caller can fall back safely.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from packages.config import get_settings
from packages.contracts.flow import (
    ComparisonRow,
    ComparisonTable,
    ContentBrief,
    DraftSection,
    FAQItem,
    LLMArticlePayload,
)
from packages.providers.base import GenerationContext, LLMOutputError, ProviderUnavailable
from packages.providers.fixtures import content_library


class DemoLLMProvider:
    name = "demo-content-library"

    def generate_article(self, brief: ContentBrief, ctx: GenerationContext) -> LLMArticlePayload:
        doc = content_library().get(brief.intent_key)
        if doc is None:
            return template_draft(brief, ctx)
        table = None
        if doc.get("table"):
            t = doc["table"]
            table = ComparisonTable(
                caption=t["caption"], columns=t["columns"],
                rows=[ComparisonRow(dimension=r["dimension"], values=r["values"], verification=r["verification"]) for r in t["rows"]],
            )
        return LLMArticlePayload(
            title=doc["title"], meta_description=" ".join(doc["meta_description"].split()), h1=doc["h1"],
            introduction=doc["introduction"].strip(),
            sections=[DraftSection(heading=s["heading"], level=s.get("level", 2), body=s["body"].strip()) for s in doc["sections"]],
            table=table,
            faq=[FAQItem(question=f["question"], answer=f["answer"]) for f in doc["faq"]],
            key_takeaways=doc.get("key_takeaways", []),
        )

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        return {"provider": self.name, "notes": ["Advisory LLM review not configured (demo provider)."], "risk": "n/a"}


def template_draft(brief: ContentBrief, ctx: GenerationContext) -> LLMArticlePayload:
    """Conservative skeleton for intents without a library entry (e.g. live discovery).

    Intentionally plain and marked for editing - the compliance gate will route it to REVIEW.
    """
    cite = f"[[E:{ctx.evidence[0].key}]]" if ctx.evidence else ""
    sections = [
        DraftSection(heading=s.heading, level=s.level,
                     body=f"EDITOR DRAFT - {s.purpose}. Add verified facts from the evidence bundle before publication.{cite}")
        for s in brief.outline
    ]
    return LLMArticlePayload(
        title=brief.recommended_title[:120].ljust(10, "."),
        meta_description=f"Editor draft for '{brief.target_keyword}': {brief.angle}. {brief.audience}."[:165].ljust(50, "."),
        h1=brief.recommended_title[:140].ljust(10, "."),
        introduction=(f"This draft addresses the search '{brief.target_keyword}'. It was produced from a template because no "
                      "model or curated draft was available, and it must be completed by an editor."),
        sections=sections or [DraftSection(heading="Overview", body="EDITOR DRAFT - outline pending.")] * 3,
        faq=[FAQItem(question=q, answer="EDITOR DRAFT - answer pending verification.")
             for q in (brief.questions_to_answer + [f"What should readers verify about '{brief.target_keyword}'?",
                                                    "Which official sources apply?", "What are the risks?"])[:3]],
    )


SYSTEM_PROMPT = """You are a careful financial-education writer for an Indian audience.
Return ONLY a JSON object matching this schema:
{"title": str(10-120), "meta_description": str(50-170), "h1": str, "introduction": str(>=80 chars),
 "sections": [{"heading": str, "level": 2|3, "body": markdown str}] (>=4),
 "table": null | {"caption": str, "columns": [str], "rows": [{"dimension": str, "values": [str], "verification": str}]},
 "faq": [{"question": str, "answer": str}] (>=3), "key_takeaways": [str]}
Rules (non-negotiable):
- Write in the requested language. Hinglish = Hindi in Latin script.
- Cite facts ONLY with the provided evidence keys using the exact token [[E:key]]. Never invent sources, numbers, licences or fees.
- If a fact is not in the evidence, omit it or say it could not be verified.
- Internal links ONLY from the provided list using [[L:intent_key|anchor text]].
- Never promise profits or returns, never call trading risk-free/safe, no first-person reviews, no ratings, no account-opening or bonus calls-to-action.
- Do not state that any broker is authorised, approved or legal in India unless the evidence says so explicitly.
"""


class OpenAICompatibleLLMProvider:
    def __init__(self, base_url: str, model: str, api_key: str = "", max_retries: int = 2, timeout: float = 180.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_retries = max_retries
        self.timeout = timeout
        self.name = f"openai-compatible:{model}"

    def _chat(self, messages: list[dict[str, str]]) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions",
                json={"model": self.model, "messages": messages, "temperature": 0.3, "response_format": {"type": "json_object"}},
                headers=headers, timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise ProviderUnavailable(f"LLM endpoint unavailable: {exc}") from exc

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        text = text.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError("no JSON object in model output")
        return json.loads(text[start : end + 1])

    def generate_article(self, brief: ContentBrief, ctx: GenerationContext) -> LLMArticlePayload:
        user = json.dumps({
            "brief": brief.model_dump(mode="json", exclude={"internal_links"}),
            "evidence": [{"key": e.key, "title": e.title, "publisher": e.publisher, "snippet": e.snippet,
                          "claims": [c.claim for c in e.claims]} for e in ctx.evidence],
            "internal_links": ctx.internal_link_targets,
        }, ensure_ascii=False)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
        last_error = ""
        for attempt in range(self.max_retries + 1):
            raw = self._chat(messages)
            try:
                return validate_payload(raw)
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)[:1500]
                messages += [
                    {"role": "assistant", "content": raw[:4000]},
                    {"role": "user", "content": f"Your JSON failed validation (attempt {attempt + 1}): {last_error}. Return corrected JSON only."},
                ]
        raise LLMOutputError(f"model output invalid after {self.max_retries + 1} attempts: {last_error}")

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        raw = self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}])
        try:
            return self._parse_json(raw)
        except ValueError as exc:
            raise LLMOutputError(str(exc)) from exc


def validate_payload(raw: str) -> LLMArticlePayload:
    data = OpenAICompatibleLLMProvider._parse_json(raw)
    return LLMArticlePayload.model_validate(data)


def get_llm_provider() -> DemoLLMProvider | OpenAICompatibleLLMProvider:
    s = get_settings()
    if s.llm_provider in ("ollama", "openai"):
        return OpenAICompatibleLLMProvider(s.llm_base_url, s.llm_model, s.llm_api_key)
    return DemoLLMProvider()
