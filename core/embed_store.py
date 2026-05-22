#!/usr/bin/env python3
"""SQLite-backed embedding store using text-embedding-3-large API."""

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
from openai import OpenAI


class EmbedStore:

    def __init__(self, db_path: str, api_key: str, base_url: str, model: str = "text-embedding-3-large"):
        self.db_path = db_path
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self._dim = None
        self._init_db()

    def _client(self) -> OpenAI:
        return OpenAI(api_key=self.api_key, base_url=self.base_url)

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS embeddings (term TEXT PRIMARY KEY, emb BLOB NOT NULL, dim INTEGER NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
            row = conn.execute("SELECT value FROM meta WHERE key='model'").fetchone()
            if row and row[0] != self.model:
                conn.execute("DELETE FROM embeddings")
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('model', ?)", (self.model,))
            row = conn.execute("SELECT dim FROM embeddings LIMIT 1").fetchone()
            if row:
                self._dim = row[0]

    @property
    def is_built(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] > 0

    @property
    def count(self):
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]

    def _encode(self, texts: list) -> np.ndarray:
        resp = self._client().embeddings.create(model=self.model, input=texts)
        result = np.array([d.embedding for d in resp.data], dtype=np.float32)
        if self._dim is None:
            self._dim = result.shape[1]
        return result

    def _encode_batch(self, batch: list, idx: int) -> tuple:
        client = self._client()
        resp = client.embeddings.create(model=self.model, input=batch)
        vec = np.array([d.embedding for d in resp.data], dtype=np.float32)
        return idx, vec

    def build(self, terms: list, batch_size: int = 256, progress: callable = None, workers: int = 8):
        with sqlite3.connect(self.db_path) as conn:
            existing = set(r[0] for r in conn.execute("SELECT term FROM embeddings").fetchall())
        new_terms = [t for t in terms if t not in existing]
        if not new_terms:
            return

        batches = []
        for i in range(0, len(new_terms), batch_size):
            batches.append((i, new_terms[i:i + batch_size]))
        total = len(new_terms)

        db_lock = threading.Lock()
        done_count = [0]

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self._encode_batch, batch, idx): idx for idx, batch in batches}
            for fut in as_completed(futures):
                idx, vec = fut.result()
                batch = batches[[b[0] for b in batches].index(idx)][1]
                rows = [(t, v.tobytes(), vec.shape[1]) for t, v in zip(batch, vec)]
                with db_lock:
                    with sqlite3.connect(self.db_path) as conn:
                        conn.executemany("INSERT OR REPLACE INTO embeddings (term, emb, dim) VALUES (?, ?, ?)", rows)
                done_count[0] += len(batch)
                if progress:
                    progress("loading", min(done_count[0], total), total,
                             f"术语向量库: {min(done_count[0], total)}/{total}")

    def sync(self, terms: list, batch_size: int = 256, progress: callable = None, workers: int = 8) -> tuple:
        """Sync DB to exactly match `terms`: add new entries, remove stale ones.

        Returns (added, removed) counts.
        """
        term_set = set(terms)
        with sqlite3.connect(self.db_path) as conn:
            existing = set(r[0] for r in conn.execute("SELECT term FROM embeddings").fetchall())

        to_remove = existing - term_set
        if to_remove:
            with sqlite3.connect(self.db_path) as conn:
                conn.executemany("DELETE FROM embeddings WHERE term = ?", [(t,) for t in to_remove])

        to_add = [t for t in terms if t not in existing]
        if to_add:
            self.build(to_add, batch_size=batch_size, progress=progress, workers=workers)

        return len(to_add), len(to_remove)

    def search(self, queries: list) -> list:
        query_vecs = self._encode(queries)
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT term, emb FROM embeddings").fetchall()
        terms = [r[0] for r in rows]
        emb_matrix = np.vstack([np.frombuffer(r[1], dtype=np.float32).reshape(1, -1) for r in rows])
        sim = query_vecs @ emb_matrix.T
        results = []
        for i in range(len(queries)):
            best = int(np.argmax(sim[i]))
            results.append((terms[best], round(float(sim[i][best]), 3)))
        return results
