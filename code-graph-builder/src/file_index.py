"""SQLite FTS5 file-content index for fast full-text search.

Indexes every line of every .go file in the repo, skipping vendor/
and generated files.  Queries return file:line results quickly.

Usage:
    from src.file_index import FileIndex

    idx = FileIndex("output/file-index.db", repo_root)
    idx.build()                       # one-time, ~30-60s
    results = idx.search("controller", path_prefix="pkg/", limit=60)
"""

import sqlite3
import logging
import time
from pathlib import Path

logger = logging.getLogger("chatbot")

SKIP_SEGMENTS = {"vendor", "third_party"}


class FileIndex:
    """Persistent full-text index over repo source files."""

    def __init__(self, db_path: str | Path, repo_root: str | Path):
        self.db_path = Path(db_path)
        self.repo_root = Path(repo_root)
        self._conn: sqlite3.Connection | None = None
        self._exists: bool | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), timeout=10)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
        return self._conn

    @property
    def exists(self) -> bool:
        """True if the index DB exists and has content."""
        if self._exists is not None:
            return self._exists
        if not self.db_path.exists():
            self._exists = False
            return False
        try:
            conn = self._get_conn()
            row = conn.execute("SELECT COUNT(*) FROM line_meta").fetchone()
            self._exists = row[0] > 0
            return self._exists
        except Exception:
            self._exists = False
            return False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, globs: list[str] | None = None) -> dict:
        """(Re)build the full-text index.  Returns stats dict."""
        globs = globs or ["*.go"]
        start = time.time()
        logger.info("Building file-content index …")

        # Close any existing connection before rebuilding
        self.close()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()

        # Drop and recreate — split into metadata table + external-content FTS
        conn.executescript("""
            DROP TABLE IF EXISTS fts_content;
            DROP TABLE IF EXISTS line_meta;

            CREATE TABLE line_meta (
                id   INTEGER PRIMARY KEY,
                file TEXT    NOT NULL,
                line_no INTEGER NOT NULL,
                content TEXT    NOT NULL
            );

            CREATE VIRTUAL TABLE fts_content USING fts5(
                content,
                content='line_meta',
                content_rowid='id',
                tokenize='unicode61'
            );
        """)

        total_files = 0
        total_lines = 0
        batch: list[tuple[str, int, str]] = []
        BATCH_SIZE = 50_000

        for pattern in globs:
            for fpath in self.repo_root.rglob(pattern):
                rel = fpath.relative_to(self.repo_root).as_posix()
                parts = set(rel.lower().split("/"))
                if parts & SKIP_SEGMENTS:
                    continue
                if "_generated" in rel.lower():
                    continue

                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        for line_no, line in enumerate(f, 1):
                            stripped = line.rstrip()
                            if stripped:
                                batch.append((rel, line_no, stripped))
                                total_lines += 1
                                if len(batch) >= BATCH_SIZE:
                                    conn.executemany(
                                        "INSERT INTO line_meta(file, line_no, content) VALUES (?, ?, ?)",
                                        batch,
                                    )
                                    batch.clear()
                except (OSError, PermissionError):
                    continue

                total_files += 1

        if batch:
            conn.executemany(
                "INSERT INTO line_meta(file, line_no, content) VALUES (?, ?, ?)",
                batch,
            )

        # Populate FTS from line_meta in one pass
        logger.info("Populating FTS index …")
        conn.execute(
            "INSERT INTO fts_content(rowid, content) "
            "SELECT id, content FROM line_meta"
        )

        # Build the file prefix index for fast path filtering
        conn.execute("CREATE INDEX IF NOT EXISTS idx_file ON line_meta(file)")
        conn.commit()
        self._exists = True

        elapsed = time.time() - start
        stats = {
            "files": total_files,
            "lines": total_lines,
            "elapsed_sec": round(elapsed, 1),
            "db_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 1),
        }
        logger.info(f"Index built: {stats}")
        return stats

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        path_prefix: str = "",
        limit: int = 60,
    ) -> list[tuple[str, int, str]]:
        """Search the index.  Returns list of (file, line_no, content)."""
        if not self.exists:
            return []

        conn = self._get_conn()
        fts_query = self._build_fts_query(query)

        try:
            if path_prefix:
                rows = conn.execute(
                    "SELECT m.file, m.line_no, m.content "
                    "FROM line_meta m "
                    "JOIN fts_content f ON f.rowid = m.id "
                    "WHERE fts_content MATCH ? AND m.file LIKE ? "
                    "LIMIT ?",
                    (fts_query, path_prefix + "%", limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT m.file, m.line_no, m.content "
                    "FROM line_meta m "
                    "JOIN fts_content f ON f.rowid = m.id "
                    "WHERE fts_content MATCH ? "
                    "LIMIT ?",
                    (fts_query, limit),
                ).fetchall()
            return rows
        except sqlite3.OperationalError as e:
            logger.warning(f"FTS query failed ({e}), falling back to simple search")
            safe_query = '"' + query.replace('"', '""') + '"'
            try:
                if path_prefix:
                    rows = conn.execute(
                        "SELECT m.file, m.line_no, m.content "
                        "FROM line_meta m "
                        "JOIN fts_content f ON f.rowid = m.id "
                        "WHERE fts_content MATCH ? AND m.file LIKE ? "
                        "LIMIT ?",
                        (safe_query, path_prefix + "%", limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT m.file, m.line_no, m.content "
                        "FROM line_meta m "
                        "JOIN fts_content f ON f.rowid = m.id "
                        "WHERE fts_content MATCH ? "
                        "LIMIT ?",
                        (safe_query, limit),
                    ).fetchall()
                return rows
            except sqlite3.OperationalError:
                return []

    def _build_fts_query(self, query: str) -> str:
        """Convert a user query into an FTS5 MATCH expression."""
        tokens = query.split()
        if not tokens:
            return '""'
        return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
        self._exists = None
