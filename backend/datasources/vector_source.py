"""Vector-store KnowledgeResolver — semantic retrieval via OpenAI embeddings + numpy cosine.

At registration time the resolver:
  1. Reads every `.txt`/`.md` file in `folder/`.
  2. Splits each into ~500-char chunks (paragraph-aware).
  3. Calls OpenAI's embeddings endpoint once per chunk in batches.
  4. Persists `(chunks, embeddings, mtime_signature)` to `index_path` (.npz).

`resolve()` embeds the query (uses `filters['query']`) and returns the top-k
most-similar chunks as KnowledgeFacts with `confidence` set from cosine score.

Falls back to empty results when the LLM is FakeLLMClient (no key) — logs
a warning instead of crashing.

Example source spec:

    id: policy_corpus
    kind: vector_store
    folder: backend/data/policy_corpus/
    index_path: backend/data/policy_corpus.npz
    ontology_type: PolicyExcerpt
    top_k: 3
    embed_model: text-embedding-3-small
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np
from tcs_hitl_context import KnowledgeFact, KnowledgeQuery, KnowledgeRef, LLMClient

log = logging.getLogger(__name__)


def _chunk_text(text: str, target: int = 500) -> list[str]:
    """Split on blank-line boundaries; merge small paragraphs."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    cur = ""
    for p in paragraphs:
        if len(cur) + len(p) + 2 > target and cur:
            chunks.append(cur)
            cur = p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur:
        chunks.append(cur)
    return chunks


def _folder_signature(folder: Path) -> str:
    """Cheap signature: filenames + their mtimes. Changes if any file is added/edited."""
    parts = []
    for p in sorted(folder.glob("*.md")) + sorted(folder.glob("*.txt")):
        parts.append(f"{p.name}:{int(p.stat().st_mtime)}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


class VectorStoreResolver:
    def __init__(
        self,
        *,
        source_id: str,
        folder: Path,
        index_path: Path,
        ontology_type: str = "PolicyExcerpt",
        top_k: int = 3,
        embed_model: str = "text-embedding-3-small",
        llm: Optional[LLMClient] = None,
        openai_api_key: Optional[str] = None,
    ):
        self.name = source_id
        self._folder = folder
        self._index_path = index_path
        self._ontology_type = ontology_type
        self._top_k = top_k
        self._embed_model = embed_model
        self._chunks: list[dict] = []   # [{"file": str, "chunk_id": int, "text": str}]
        self._embeddings: Optional[np.ndarray] = None  # shape (N, dim)
        self._signature: Optional[str] = None
        # We use the openai SDK directly for embeddings (LLMClient only does completions)
        self._api_key = openai_api_key
        # Build / load on init (cheap — at most one folder scan)
        self._build_or_load()

    # -------------------------------------------------------------------------
    # Index lifecycle
    # -------------------------------------------------------------------------
    def _build_or_load(self) -> None:
        if not self._folder.exists():
            log.warning("vector_store %s: folder %s does not exist", self.name, self._folder)
            return
        sig = _folder_signature(self._folder)
        if self._index_path.exists():
            try:
                blob = np.load(self._index_path, allow_pickle=True)
                stored_sig = str(blob["signature"][()])
                if stored_sig == sig:
                    self._chunks = list(blob["chunks"])
                    self._embeddings = blob["embeddings"]
                    self._signature = sig
                    log.info(
                        "vector_store %s: loaded %d chunks from %s",
                        self.name, len(self._chunks), self._index_path,
                    )
                    return
            except (KeyError, ValueError) as exc:
                log.warning("vector_store %s: index load failed (%s); rebuilding", self.name, exc)

        # Need to (re)build. Without an API key we just collect the chunks but
        # leave embeddings empty — callers will get [] from resolve() and log
        # a warning, but the rest of the app keeps running.
        chunks: list[dict] = []
        for path in sorted(self._folder.glob("*.md")) + sorted(self._folder.glob("*.txt")):
            text = path.read_text()
            for i, c in enumerate(_chunk_text(text)):
                chunks.append({"file": path.name, "chunk_id": i, "text": c})
        self._chunks = chunks

        if not self._api_key:
            log.warning(
                "vector_store %s: no OpenAI key, %d chunks indexed without embeddings",
                self.name, len(chunks),
            )
            self._signature = sig
            return

        # Embed in one batch
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)
            resp = client.embeddings.create(
                model=self._embed_model,
                input=[c["text"] for c in chunks],
            )
            self._embeddings = np.array([d.embedding for d in resp.data], dtype=np.float32)
            self._signature = sig
            np.savez(
                self._index_path,
                chunks=np.array(chunks, dtype=object),
                embeddings=self._embeddings,
                signature=np.array(sig),
            )
            log.info(
                "vector_store %s: embedded and cached %d chunks → %s",
                self.name, len(chunks), self._index_path,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("vector_store %s: embedding build failed: %s", self.name, exc)
            self._embeddings = None

    # -------------------------------------------------------------------------
    # Resolve
    # -------------------------------------------------------------------------
    def resolve(self, query: KnowledgeQuery) -> list[KnowledgeFact]:
        if self._embeddings is None or not self._chunks:
            log.info(
                "vector_store %s: no embeddings available; returning empty",
                self.name,
            )
            return []
        q = str(query.filters.get("query") or query.purpose or "")
        if not q:
            return []
        # Embed the query
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self._api_key)
            resp = client.embeddings.create(model=self._embed_model, input=[q])
            qv = np.array(resp.data[0].embedding, dtype=np.float32)
        except Exception as exc:  # noqa: BLE001
            log.warning("vector_store %s: query embed failed: %s", self.name, exc)
            return []

        # Cosine similarity
        emb = self._embeddings
        sims = (emb @ qv) / (np.linalg.norm(emb, axis=1) * np.linalg.norm(qv) + 1e-9)
        k = int(query.filters.get("top_k", self._top_k))
        idx = np.argsort(-sims)[:k]

        out: list[KnowledgeFact] = []
        for i in idx:
            ch = self._chunks[int(i)]
            score = float(sims[int(i)])
            ref = KnowledgeRef(
                source=f"vector:{self.name}",
                ontology_type=query.ontology_type or self._ontology_type,
                id=f"{ch['file']}#chunk-{ch['chunk_id']}",
            )
            text = str(ch["text"])
            title = text.splitlines()[0][:80] if text else ch["file"]
            summary = text.replace("\n", " ")[:200]
            out.append(
                KnowledgeFact(
                    ref=ref,
                    payload={"title": title, "summary": summary},
                    fetched_by=self.name,
                    confidence=round(score, 4),
                )
            )
        return out

    def sample(self, n: int = 3) -> list[KnowledgeFact]:
        # Return the first n chunks (no embeddings needed for the probe view)
        out: list[KnowledgeFact] = []
        for ch in self._chunks[:n]:
            text = str(ch["text"])
            title = text.splitlines()[0][:80] if text else ch["file"]
            summary = text.replace("\n", " ")[:200]
            out.append(
                KnowledgeFact(
                    ref=KnowledgeRef(
                        source=f"vector:{self.name}",
                        ontology_type=self._ontology_type,
                        id=f"{ch['file']}#chunk-{ch['chunk_id']}",
                    ),
                    payload={"title": title, "summary": summary},
                    fetched_by=self.name,
                )
            )
        return out
