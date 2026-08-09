import os

import psycopg
from psycopg.rows import dict_row


def get_conn():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)


def ping() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1")


def create_batch() -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO batches DEFAULT VALUES RETURNING id")
        return cur.fetchone()["id"]


def batch_exists(batch_id: int) -> bool:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1 FROM batches WHERE id = %s", (batch_id,))
        return cur.fetchone() is not None


def add_document(
    batch_id: int,
    filename: str,
    file_path: str,
    num_pages: int,
    pages_to_process: int,
    title: str | None = None,
    source_url: str | None = None,
) -> int:
    """Insert a document and one row per page. Pages beyond pages_to_process are
    inserted as 'skipped' up front rather than queued — trial page-cap, not an error."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (batch_id, filename, title, source_url, file_path, num_pages, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'queued')
            RETURNING id
            """,
            (batch_id, filename, title, source_url, file_path, num_pages),
        )
        document_id = cur.fetchone()["id"]
        cur.executemany(
            "INSERT INTO pages (document_id, page_number, status) VALUES (%s, %s, %s)",
            [
                (document_id, page_number, "queued" if page_number <= pages_to_process else "skipped")
                for page_number in range(1, num_pages + 1)
            ],
        )
        return document_id


def fetch_next_queued_page():
    """Claim the oldest queued page and mark it (and its document) as processing."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.id, p.document_id, p.page_number, d.file_path, d.batch_id
            FROM pages p
            JOIN documents d ON d.id = p.document_id
            WHERE p.status = 'queued'
            ORDER BY p.id ASC
            LIMIT 1
            """
        )
        page = cur.fetchone()
        if page is None:
            return None
        cur.execute("UPDATE pages SET status = 'processing' WHERE id = %s", (page["id"],))
        cur.execute(
            """
            UPDATE documents
            SET status = 'processing', started_at = COALESCE(started_at, now())
            WHERE id = %s
            """,
            (page["document_id"],),
        )
        return page


def recover_orphaned_pages() -> int:
    """Requeue pages left in 'processing' by a worker that crashed mid-page."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE pages SET status = 'queued' WHERE status = 'processing'")
        return cur.rowcount


def recover_orphaned_facts() -> list[int]:
    """Reset documents left in 'generating' by a worker that crashed mid-fact-generation.
    Returns their ids so the caller can re-trigger generation for them."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE documents SET facts_status = 'pending' WHERE facts_status = 'generating' RETURNING id")
        return [row["id"] for row in cur.fetchall()]


def find_cached_page(content_hash: str):
    """Most recent successfully-OCR'd page with this exact rendered-image content."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ocr_text, char_count, word_count
            FROM pages
            WHERE content_hash = %s AND status = 'done'
            ORDER BY id DESC
            LIMIT 1
            """,
            (content_hash,),
        )
        return cur.fetchone()


def save_page_result(
    page_id: int, text: str, char_count: int, word_count: int, content_hash: str, from_cache: bool = False
) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pages
            SET status = 'done', ocr_text = %s, char_count = %s, word_count = %s,
                content_hash = %s, from_cache = %s, finished_at = now()
            WHERE id = %s
            """,
            (text, char_count, word_count, content_hash, from_cache, page_id),
        )


def save_page_error(page_id: int, error_message: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE pages
            SET status = 'error', error_message = %s, finished_at = now()
            WHERE id = %s
            """,
            (error_message, page_id),
        )


def refresh_document_progress(document_id: int) -> str:
    """Recompute a document's aggregate stats from its pages, roll its status forward,
    and return the new status so the caller can react to a done/error transition."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE status = 'done') AS done_count,
                count(*) FILTER (WHERE status = 'error') AS error_count,
                count(*) FILTER (WHERE status = 'skipped') AS skipped_count,
                count(*) AS total,
                coalesce(sum(char_count) FILTER (WHERE status = 'done'), 0) AS char_count,
                coalesce(sum(word_count) FILTER (WHERE status = 'done'), 0) AS word_count
            FROM pages
            WHERE document_id = %s
            """,
            (document_id,),
        )
        row = cur.fetchone()
        finished_count = row["done_count"] + row["error_count"] + row["skipped_count"]
        all_finished = finished_count == row["total"]
        if all_finished:
            status = "error" if row["error_count"] > 0 else "done"
        elif finished_count > 0:
            status = "processing"
        else:
            status = "queued"
        cur.execute(
            """
            UPDATE documents
            SET pages_done = %s,
                char_count = %s,
                word_count = %s,
                status = %s,
                finished_at = CASE WHEN %s THEN now() ELSE finished_at END
            WHERE id = %s
            """,
            (finished_count, row["char_count"], row["word_count"], status, all_finished, document_id),
        )
        return status


def claim_document_facts(document_id: int) -> bool:
    """Atomically flip a document from 'pending' to 'generating'. Returns True only for
    the caller that wins the flip, so fact generation runs at most once per document."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE documents SET facts_status = 'generating' WHERE id = %s AND facts_status = 'pending' RETURNING id",
            (document_id,),
        )
        return cur.fetchone() is not None


def set_document_facts_status(document_id: int, status: str) -> None:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE documents SET facts_status = %s WHERE id = %s", (status, document_id))


def get_document_with_text(document_id: int):
    """The document plus all its successfully-OCR'd page text concatenated."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.batch_id, d.title, d.filename,
                   string_agg(p.ocr_text, E'\n' ORDER BY p.page_number) FILTER (WHERE p.status = 'done') AS ocr_text
            FROM documents d
            LEFT JOIN pages p ON p.document_id = d.id
            WHERE d.id = %s
            GROUP BY d.id, d.batch_id, d.title, d.filename
            """,
            (document_id,),
        )
        return cur.fetchone()


def save_facts(facts: list[tuple[int, int, str, str]]) -> None:
    """Each item: (batch_id, document_id, category, fact_text)."""
    if not facts:
        return
    with get_conn() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO facts (batch_id, document_id, category, fact_text) VALUES (%s, %s, %s, %s)",
            facts,
        )


def get_facts(batch_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.id, f.document_id, f.category, f.fact_text,
                   coalesce(d.title, d.filename) AS document_title, d.source_url
            FROM facts f
            JOIN documents d ON d.id = f.document_id
            WHERE f.batch_id = %s
            ORDER BY f.id ASC
            """,
            (batch_id,),
        )
        return cur.fetchall()


def get_document(document_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, batch_id, filename, title, status, facts_status,
                   num_pages, pages_done, char_count, word_count, error_message
            FROM documents
            WHERE id = %s
            """,
            (document_id,),
        )
        return cur.fetchone()


def get_pages(document_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT page_number, status, char_count, word_count, from_cache,
                   left(coalesce(ocr_text, ''), 200) AS text_preview
            FROM pages
            WHERE document_id = %s
            ORDER BY page_number ASC
            """,
            (document_id,),
        )
        return cur.fetchall()


def get_batch(batch_id: int):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, created_at FROM batches WHERE id = %s", (batch_id,))
        batch = cur.fetchone()
        if batch is None:
            return None
        cur.execute(
            """
            SELECT d.id, d.filename, d.title, d.status, d.facts_status, d.num_pages, d.pages_done,
                   d.char_count, d.word_count, d.error_message,
                   (SELECT left(coalesce(p.ocr_text, ''), 150) FROM pages p
                    WHERE p.document_id = d.id AND p.page_number = 1) AS text_preview
            FROM documents d
            WHERE d.batch_id = %s
            ORDER BY d.id ASC
            """,
            (batch_id,),
        )
        batch["documents"] = cur.fetchall()
        # Facts arrive incrementally per-document (see documents[].facts_status),
        # so the batch just exposes whatever has landed so far.
        batch["facts"] = get_facts(batch_id)
        return batch
