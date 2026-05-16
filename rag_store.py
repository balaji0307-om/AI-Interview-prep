from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass


try:
    import chromadb
except ModuleNotFoundError:
    chromadb = None

try:
    import faiss
except ModuleNotFoundError:
    faiss = None


VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "memory").strip().lower()
CHROMA_PATH = os.getenv("CHROMA_PATH", ".chroma").strip()
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "interview_prep").strip()


@dataclass(frozen=True)
class RagDocument:
    id: str
    text: str
    metadata: dict[str, str]


_documents: list[RagDocument] = []
_chroma_collection = None
_faiss_index = None
_faiss_documents: list[RagDocument] = []


def vector_backend_name() -> str:
    if VECTOR_BACKEND == "chroma" and chromadb is not None:
        return "chroma"
    if VECTOR_BACKEND == "faiss" and faiss is not None:
        return "faiss"
    return "memory"


def _embedding(text: str, dimensions: int = 128) -> list[float]:
    vector = [0.0] * dimensions
    for term in re.findall(r"[a-z0-9+#]+", text.lower()):
        digest = hashlib.sha256(term.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dimensions
        vector[index] += 1.0
    length = sum(value * value for value in vector) ** 0.5
    if not length:
        return vector
    return [value / length for value in vector]


def _chroma():
    global _chroma_collection
    if _chroma_collection is None and chromadb is not None:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _chroma_collection = client.get_or_create_collection(CHROMA_COLLECTION)
    return _chroma_collection


def _faiss():
    global _faiss_index
    if _faiss_index is None and faiss is not None:
        _faiss_index = faiss.IndexFlatIP(128)
    return _faiss_index


def index_documents(documents: list[RagDocument]) -> int:
    backend = vector_backend_name()
    if backend == "chroma":
        collection = _chroma()
        if collection is None:
            return 0
        existing = {item for item in collection.get(ids=[document.id for document in documents]).get("ids", [])}
        fresh = [document for document in documents if document.id not in existing]
        if fresh:
            collection.add(
                ids=[document.id for document in fresh],
                documents=[document.text for document in fresh],
                metadatas=[document.metadata for document in fresh],
                embeddings=[_embedding(document.text) for document in fresh],
            )
        return len(fresh)

    if backend == "faiss":
        index = _faiss()
        if index is None:
            return 0
        known_ids = {document.id for document in _faiss_documents}
        fresh = [document for document in documents if document.id not in known_ids]
        if fresh:
            import numpy as np

            vectors = np.array([_embedding(document.text) for document in fresh], dtype="float32")
            index.add(vectors)
            _faiss_documents.extend(fresh)
        return len(fresh)

    known_ids = {document.id for document in _documents}
    added = 0
    for document in documents:
        if document.id in known_ids:
            continue
        _documents.append(document)
        known_ids.add(document.id)
        added += 1
    return added


def index_document_payloads(payloads: list[dict[str, object]]) -> int:
    documents = [
        RagDocument(
            id=str(payload["id"]),
            text=str(payload["text"]),
            metadata={str(key): str(value) for key, value in dict(payload.get("metadata", {})).items()},
        )
        for payload in payloads
    ]
    return index_documents(documents)


def _metadata_matches(document: RagDocument, user_id: str | None) -> bool:
    owner = document.metadata.get("user_id", "public")
    return owner in {"public", str(user_id or "")}


def search(query: str, limit: int = 4, user_id: str | None = None) -> list[RagDocument]:
    backend = vector_backend_name()
    if backend == "chroma":
        collection = _chroma()
        if collection is None:
            return []
        result = collection.query(query_embeddings=[_embedding(query)], n_results=limit * 3)
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        rows = [RagDocument(id=item_id, text=text, metadata=dict(metadata or {})) for item_id, text, metadata in zip(ids, documents, metadatas)]
        return [document for document in rows if _metadata_matches(document, user_id)][:limit]

    if backend == "faiss":
        index = _faiss()
        if index is None or index.ntotal == 0:
            return []
        import numpy as np

        query_vector = np.array([_embedding(query)], dtype="float32")
        _, indexes = index.search(query_vector, min(limit * 3, index.ntotal))
        rows = [_faiss_documents[index] for index in indexes[0] if 0 <= index < len(_faiss_documents)]
        return [document for document in rows if _metadata_matches(document, user_id)][:limit]

    terms = {term for term in re.findall(r"[a-z0-9+#]+", query.lower()) if len(term) > 2}
    if not terms:
        return []
    scored: list[tuple[int, RagDocument]] = []
    for document in _documents:
        if not _metadata_matches(document, user_id):
            continue
        haystack = document.text.lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            scored.append((score, document))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [document for _, document in scored[:limit]]
