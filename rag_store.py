import os
import sqlite3
import json
import httpx
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("RAG_DB_PATH", Path(__file__).resolve().parent / "rag_memory.db"))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", os.environ.get("EMBEDDING_MODEL", "embeddinggemma-2"))
FALLBACK_EMBED_MODEL = "nomic-embed-text"


def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_rag_db():
    conn = get_db()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                channel_id INTEGER,
                author TEXT,
                timestamp TEXT,
                content TEXT NOT NULL,
                embedding BLOB NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_channel ON rag_chunks(channel_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_source ON rag_chunks(source);")
    conn.close()


async def embed_text(text: str) -> list[float] | None:
    """Generate vector embedding for text using Ollama (supports embeddinggemma-2 with fallback)."""
    if not text or not text.strip():
        return None
    url = f"{OLLAMA_BASE_URL}/api/embeddings"
    models_to_try = [EMBED_MODEL] if EMBED_MODEL == FALLBACK_EMBED_MODEL else [EMBED_MODEL, FALLBACK_EMBED_MODEL]
    for model in models_to_try:
        payload = {"model": model, "prompt": text.strip()}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    emb = data.get("embedding")
                    if emb:
                        return emb
        except Exception as e:
            if model == FALLBACK_EMBED_MODEL:
                print(f"Error generating embedding via Ollama ({model}): {e}")
    return None


def sync_embed_text(text: str) -> list[float] | None:
    """Synchronous version of embed_text for batch indexing scripts."""
    if not text or not text.strip():
        return None
    url = f"{OLLAMA_BASE_URL}/api/embeddings"
    models_to_try = [EMBED_MODEL] if EMBED_MODEL == FALLBACK_EMBED_MODEL else [EMBED_MODEL, FALLBACK_EMBED_MODEL]
    for model in models_to_try:
        payload = {"model": model, "prompt": text.strip()}
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    emb = data.get("embedding")
                    if emb:
                        return emb
        except Exception as e:
            if model == FALLBACK_EMBED_MODEL:
                print(f"Error generating sync embedding via Ollama ({model}): {e}")
    return None


def add_chunk(content: str, embedding: list[float], source: str = "history", channel_id: int | None = None, author: str | None = None, timestamp: str | None = None):
    """Insert a single text chunk and its embedding vector into SQLite."""
    if not content or not embedding:
        return
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).isoformat()
    
    vector_blob = np.array(embedding, dtype=np.float32).tobytes()
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO rag_chunks (source, channel_id, author, timestamp, content, embedding) VALUES (?, ?, ?, ?, ?, ?)",
            (source, channel_id, author, timestamp, content, vector_blob)
        )
    conn.close()


def query_rag(query_embedding: list[float], top_k: int = 4, channel_id: int | None = None) -> list[dict]:
    """Perform fast numpy vector cosine similarity search over stored SQLite chunks."""
    if not query_embedding:
        return []
    
    q_vec = np.array(query_embedding, dtype=np.float32)
    q_norm = np.linalg.norm(q_vec)
    if q_norm == 0:
        return []
    
    conn = get_db()
    cursor = conn.cursor()
    
    if channel_id:
        cursor.execute("SELECT id, source, channel_id, author, timestamp, content, embedding FROM rag_chunks WHERE channel_id = ? OR channel_id IS NULL", (channel_id,))
    else:
        cursor.execute("SELECT id, source, channel_id, author, timestamp, content, embedding FROM rag_chunks")
        
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return []

    results = []
    for r_id, source, c_id, author, ts, content, blob in rows:
        vec = np.frombuffer(blob, dtype=np.float32)
        norm = np.linalg.norm(vec)
        if norm > 0:
            sim = float(np.dot(q_vec, vec) / (q_norm * norm))
            results.append({
                "id": r_id,
                "source": source,
                "channel_id": c_id,
                "author": author,
                "timestamp": ts,
                "content": content,
                "score": sim
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


# Initialize DB on module import
init_rag_db()
