from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor
import requests
from requests import HTTPError, RequestException

from config import settings


_AUDIENCE_BY_PREFIX = {
    "admin": "admin",
    "doctor": "doctor",
    "patient": "patient",
}


@dataclass
class RetrievedChunk:
    audience: str
    title: str
    source_path: str
    chunk_index: int
    content: str
    score: float


class RoleKnowledgeBase:
    """Minimal pgvector-backed store for role-scoped RAG retrieval."""

    def __init__(self) -> None:
        self._api_key = __import__("os").environ.get("GEMINI_API_KEY")
        self._host = settings.RAG_POSTGRES_HOST
        self._port = settings.RAG_POSTGRES_PORT
        self._db = settings.RAG_POSTGRES_DB
        self._user = settings.RAG_POSTGRES_USER
        self._password = settings.RAG_POSTGRES_PASSWORD
        self._sslmode = settings.RAG_POSTGRES_SSLMODE
        self._table = self._validate_table_name(settings.RAG_TABLE)
        self._docs_dir = Path(settings.RAG_DOCS_DIR)
        self._embed_model = settings.RAG_EMBED_MODEL
        self._embed_dim = settings.RAG_EMBED_DIM
        self._top_k = settings.RAG_TOP_K

    @staticmethod
    def _validate_table_name(table_name: str) -> str:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
            raise ValueError("RAG_TABLE must contain only letters, numbers, and underscores.")
        return table_name

    @property
    def enabled(self) -> bool:
        return all([self._api_key, self._host, self._db, self._user, self._password])

    def _connect(self):
        return psycopg2.connect(
            host=self._host,
            port=self._port,
            dbname=self._db,
            user=self._user,
            password=self._password,
            sslmode=self._sslmode,
        )

    def ensure_schema(self) -> None:
        if not self.enabled:
            raise ValueError("RAG storage is not configured. Set the RAG_POSTGRES_* variables and GEMINI_API_KEY.")
        sql = f"""
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE IF NOT EXISTS {self._table} (
            chunk_id BIGSERIAL PRIMARY KEY,
            audience VARCHAR(20) NOT NULL,
            title TEXT NOT NULL,
            source_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding VECTOR({self._embed_dim}) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (source_path, chunk_index)
        );
        CREATE INDEX IF NOT EXISTS idx_{self._table}_audience ON {self._table}(audience);
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()

    @staticmethod
    def _read_title(content: str, fallback: str) -> str:
        for line in content.splitlines():
            if line.startswith("#"):
                return line.lstrip("#").strip()
        return fallback

    @staticmethod
    def _chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
        clean = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not clean:
            return []
        chunks: list[str] = []
        start = 0
        while start < len(clean):
            end = min(len(clean), start + chunk_size)
            if end < len(clean):
                split_at = clean.rfind("\n\n", start, end)
                if split_at == -1:
                    split_at = clean.rfind(". ", start, end)
                if split_at != -1 and split_at > start + 200:
                    end = split_at + 1
            chunk = clean[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(clean):
                break
            start = max(end - overlap, start + 1)
        return chunks

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"

    def _embed_text(self, text: str, *, task_type: str = "RETRIEVAL_DOCUMENT", title: str | None = None) -> list[float]:
        """Generate an embedding vector via the Gemini Embeddings API (free tier)."""
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY is required for embedding generation.")
        response = None
        try:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/{self._embed_model}:embedContent",
                headers={
                    "x-goog-api-key": self._api_key,
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._embed_model,
                    "content": {"parts": [{"text": text}]},
                    "taskType": task_type,
                    "title": title,
                    "outputDimensionality": self._embed_dim,
                },
                timeout=60,
            )
            response.raise_for_status()
        except HTTPError as exc:
            detail = ""
            try:
                detail = response.json().get("error", {}).get("message", "") if response is not None else ""
            except ValueError:
                detail = response.text if response is not None else ""
            raise ValueError(detail or "Failed to generate embeddings with Gemini.") from exc
        except RequestException as exc:
            raise ValueError("Could not reach the Gemini embedding endpoint. Check network access.") from exc
        payload = response.json()
        values = payload.get("embedding", {}).get("values")
        if not values:
            raise ValueError("Gemini did not return an embedding vector.")
        return self._normalize([float(v) for v in values])

    def _iter_documents(self, docs_dir: Path | None = None) -> list[dict[str, Any]]:
        root = docs_dir or self._docs_dir
        if not root.exists():
            raise ValueError(f"Knowledge document directory not found: {root}")
        documents: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.md")):
            prefix = path.stem.split("_", 1)[0].lower()
            audience = _AUDIENCE_BY_PREFIX.get(prefix)
            if not audience:
                continue
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                continue
            documents.append(
                {
                    "audience": audience,
                    "title": self._read_title(content, path.stem.replace("_", " ").title()),
                    "source_path": str(path),
                    "content": content,
                }
            )
        return documents

    def index_documents(self, docs_dir: Path | None = None) -> dict[str, int]:
        self.ensure_schema()
        docs = self._iter_documents(docs_dir)
        inserted = 0
        with self._connect() as conn:
            with conn.cursor() as cur:
                for doc in docs:
                    cur.execute(f"DELETE FROM {self._table} WHERE source_path = %s", (doc["source_path"],))
                    for chunk_index, chunk in enumerate(self._chunk_text(doc["content"])):
                        embedding = self._embed_text(
                            chunk,
                            task_type="RETRIEVAL_DOCUMENT",
                            title=doc["title"],
                        )
                        cur.execute(
                            f"""
                            INSERT INTO {self._table} (
                                audience, title, source_path, chunk_index, content, metadata, embedding
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s::vector)
                            ON CONFLICT (source_path, chunk_index)
                            DO UPDATE SET
                                audience = EXCLUDED.audience,
                                title = EXCLUDED.title,
                                content = EXCLUDED.content,
                                metadata = EXCLUDED.metadata,
                                embedding = EXCLUDED.embedding
                            """,
                            (
                                doc["audience"],
                                doc["title"],
                                doc["source_path"],
                                chunk_index,
                                chunk,
                                Json({"audience": doc["audience"], "title": doc["title"]}),
                                self._vector_literal(embedding),
                            ),
                        )
                        inserted += 1
            conn.commit()
        return {"documents_indexed": len(docs), "chunks_indexed": inserted}

    def search(self, query: str, audience: str, top_k: int | None = None) -> list[RetrievedChunk]:
        if not self.enabled:
            return []
        self.ensure_schema()
        query_embedding = self._embed_text(query, task_type="RETRIEVAL_QUERY")
        results: list[RetrievedChunk] = []
        with self._connect() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""
                    SELECT
                        audience,
                        title,
                        source_path,
                        chunk_index,
                        content,
                        1 - (embedding <=> %s::vector) AS score
                    FROM {self._table}
                    WHERE audience = %s
                    ORDER BY embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (
                        self._vector_literal(query_embedding),
                        audience,
                        self._vector_literal(query_embedding),
                        top_k or self._top_k,
                    ),
                )
                rows = cur.fetchall()
        for row in rows:
            results.append(
                RetrievedChunk(
                    audience=row["audience"],
                    title=row["title"],
                    source_path=row["source_path"],
                    chunk_index=row["chunk_index"],
                    content=row["content"],
                    score=float(row["score"]),
                )
            )
        return results

    @staticmethod
    def render_context(chunks: list[RetrievedChunk]) -> str:
        if not chunks:
            return "No retrieved policy or process documents were available."
        lines = []
        for index, chunk in enumerate(chunks, start=1):
            lines.append(
                f"[Source {index}] {chunk.title} | {chunk.source_path} | chunk {chunk.chunk_index}\n{chunk.content}"
            )
        return "\n\n".join(lines)
