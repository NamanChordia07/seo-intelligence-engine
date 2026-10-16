"""Lightweight, dependency-free semantic embeddings.

A feature-hashing embedder over *concept tokens* (multilingual lexicon concepts,
entities and transliterated words) plus character trigrams. It is deterministic,
instant, runs anywhere and stores in pgvector (``vector(256)``). Because concepts
are shared across English / Hindi / Hinglish, cross-language paraphrases land
close together - which a plain bag-of-words model could not do.

A heavier neural embedder (e.g. a multilingual sentence-transformer or an Ollama
embedding model) can be swapped in via ``Embedder`` without touching callers.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol

from packages.persistence.models import EMBEDDING_DIM


class Embedder(Protocol):
    name: str

    def embed(self, tokens: list[str]) -> list[float]: ...


def _bucket(feature: str) -> tuple[int, float]:
    h = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    idx = int.from_bytes(h[:4], "little") % EMBEDDING_DIM
    sign = 1.0 if h[4] & 1 else -1.0
    return idx, sign


class ConceptHashEmbedder:
    name = "concept-hash-v1"

    def embed(self, tokens: list[str]) -> list[float]:
        vec = [0.0] * EMBEDDING_DIM
        for tok in tokens:
            if tok.startswith("C:"):
                weight = 3.0
            elif tok.startswith("E:"):
                weight = 2.5
            else:
                weight = 1.0
            idx, sign = _bucket(tok)
            vec[idx] += sign * weight
            if not tok.startswith(("C:", "E:")) and len(tok) > 4:
                padded = f"#{tok}#"
                for i in range(len(padded) - 2):
                    j, s = _bucket("3g:" + padded[i : i + 3])
                    vec[j] += s * 0.15
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def cosine(a: list[float] | None, b: list[float] | None) -> float:
    if a is None or b is None:
        return 0.0
    a, b = list(a), list(b)
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


_default = ConceptHashEmbedder()


def get_embedder() -> Embedder:
    return _default
