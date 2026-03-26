"""SQLite FTS5 index for Kubernetes documentation (markdown files).

Indexes each document with its title (from Hugo frontmatter) and full text.
Queries return document-level results with titles and snippets.

Usage:
    from src.doc_index import DocIndex

    idx = DocIndex("output/doc-index.db", docs_root)
    idx.build()
    results = idx.search("pod lifecycle")
"""

import re
import sqlite3
import logging
import time
from pathlib import Path

logger = logging.getLogger("chatbot")


def _extract_frontmatter(text: str) -> tuple[str, str]:
    """Extract title from Hugo YAML frontmatter. Returns (title, body)."""
    if not text.startswith("---"):
        return "", text
    end = text.find("---", 3)
    if end == -1:
        return "", text
    frontmatter = text[3:end]
    body = text[end + 3:].strip()

    title = ""
    for line in frontmatter.splitlines():
        line = line.strip()
        if line.lower().startswith("title:"):
            title = line[6:].strip().strip('"').strip("'")
            break
    return title, body


def _strip_hugo_shortcodes(text: str) -> str:
    """Remove Hugo shortcodes like {{< ... >}} and {{% ... %}} for cleaner indexing."""
    text = re.sub(r'\{\{[<%].*?[%>]\}\}', '', text)
    return text


def _doc_path_to_url(rel_path: str) -> str:
    """Convert a relative doc path to a kubernetes.io URL path.

    e.g. concepts/workloads/pods/pod-lifecycle.md
      -> /docs/concepts/workloads/pods/pod-lifecycle/
    """
    # Strip _index.md → directory URL
    url = rel_path.replace("\\", "/")
    if url.endswith("/_index.md"):
        url = url[:-len("/_index.md")] + "/"
    elif url.endswith(".md"):
        url = url[:-3] + "/"
    if not url.startswith("/"):
        url = "/" + url
    return "/docs" + url


class DocIndex:
    """Persistent full-text index over Kubernetes documentation."""

    def __init__(self, db_path: str | Path, docs_root: str | Path):
        self.db_path = Path(db_path)
        self.docs_root = Path(docs_root)
        self._conn: sqlite3.Connection | None = None
        self._exists: bool | None = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), timeout=10)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA mmap_size=268435456")
        return self._conn

    @property
    def exists(self) -> bool:
        if self._exists is not None:
            return self._exists
        if not self.db_path.exists():
            self._exists = False
            return False
        try:
            conn = self._get_conn()
            row = conn.execute("SELECT COUNT(*) FROM docs").fetchone()
            self._exists = row[0] > 0
            return self._exists
        except Exception:
            self._exists = False
            return False

    def build(self) -> dict:
        """(Re)build the documentation index. Returns stats dict."""
        start = time.time()
        logger.info("Building documentation index …")

        self.close()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()

        conn.executescript("""
            DROP TABLE IF EXISTS docs_fts;
            DROP TABLE IF EXISTS docs;

            CREATE TABLE docs (
                id      INTEGER PRIMARY KEY,
                file    TEXT NOT NULL,
                title   TEXT NOT NULL,
                url     TEXT NOT NULL,
                content TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE docs_fts USING fts5(
                title,
                content,
                content='docs',
                content_rowid='id',
                tokenize='unicode61'
            );
        """)

        total = 0
        for md_file in self.docs_root.rglob("*.md"):
            rel = md_file.relative_to(self.docs_root).as_posix()

            try:
                text = md_file.read_text(encoding="utf-8", errors="ignore")
            except (OSError, PermissionError):
                continue

            title, body = _extract_frontmatter(text)
            body = _strip_hugo_shortcodes(body)

            if not title:
                # Use filename as fallback title
                title = md_file.stem.replace("-", " ").replace("_", " ").title()

            url = _doc_path_to_url(rel)

            conn.execute(
                "INSERT INTO docs(file, title, url, content) VALUES (?, ?, ?, ?)",
                (rel, title, url, body),
            )
            total += 1

        # Populate FTS
        logger.info("Populating docs FTS index …")
        conn.execute(
            "INSERT INTO docs_fts(rowid, title, content) "
            "SELECT id, title, content FROM docs"
        )
        conn.commit()
        self._exists = True

        elapsed = time.time() - start
        stats = {
            "docs": total,
            "elapsed_sec": round(elapsed, 1),
            "db_size_mb": round(self.db_path.stat().st_size / 1024 / 1024, 1),
        }
        logger.info(f"Doc index built: {stats}")
        return stats

    def search(self, query: str, *, limit: int = 10) -> list[dict]:
        """Search docs. Returns list of {file, title, url, snippet}."""
        if not self.exists:
            return []

        conn = self._get_conn()
        fts_query = self._build_fts_query(query)

        try:
            rows = conn.execute(
                "SELECT d.file, d.title, d.url, snippet(docs_fts, 1, '»', '«', '…', 40) "
                "FROM docs d "
                "JOIN docs_fts f ON f.rowid = d.id "
                "WHERE docs_fts MATCH ? "
                "ORDER BY rank "
                "LIMIT ?",
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError as e:
            logger.warning(f"Doc FTS query failed ({e}), trying quoted")
            safe = '"' + query.replace('"', '""') + '"'
            try:
                rows = conn.execute(
                    "SELECT d.file, d.title, d.url, snippet(docs_fts, 1, '»', '«', '…', 40) "
                    "FROM docs d "
                    "JOIN docs_fts f ON f.rowid = d.id "
                    "WHERE docs_fts MATCH ? "
                    "ORDER BY rank "
                    "LIMIT ?",
                    (safe, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                return []

        return [
            {"file": r[0], "title": r[1], "url": r[2], "snippet": r[3]}
            for r in rows
        ]

    def get_doc(self, file_path: str) -> dict | None:
        """Get full content of a specific doc by relative file path."""
        if not self.exists:
            return None
        conn = self._get_conn()
        row = conn.execute(
            "SELECT file, title, url, content FROM docs WHERE file = ?",
            (file_path,),
        ).fetchone()
        if row:
            return {"file": row[0], "title": row[1], "url": row[2], "content": row[3]}
        return None

    def _build_fts_query(self, query: str) -> str:
        tokens = query.split()
        if not tokens:
            return '""'
        return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
        self._exists = None
