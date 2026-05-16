from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RagDocument:
    id: str
    text: str
    metadata: dict[str, str]


_documents: list[RagDocument] = []


def index_documents(documents: list[RagDocument]) -> int:
    known_ids = {document.id for document in _documents}
    added = 0
    for document in documents:
        if document.id in known_ids:
            continue
        _documents.append(document)
        known_ids.add(document.id)
        added += 1
    return added


def search(query: str, limit: int = 4) -> list[RagDocument]:
    terms = {term for term in re.findall(r"[a-z0-9+#]+", query.lower()) if len(term) > 2}
    if not terms:
        return []
    scored: list[tuple[int, RagDocument]] = []
    for document in _documents:
        haystack = document.text.lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            scored.append((score, document))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [document for _, document in scored[:limit]]
