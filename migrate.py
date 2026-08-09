import os

import psycopg

DDL = """
CREATE TABLE IF NOT EXISTS batches (
    id SERIAL PRIMARY KEY,
    facts_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    title TEXT,
    file_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    facts_status TEXT NOT NULL DEFAULT 'pending',
    num_pages INTEGER NOT NULL DEFAULT 0,
    pages_done INTEGER NOT NULL DEFAULT 0,
    char_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS pages (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    char_count INTEGER NOT NULL DEFAULT 0,
    word_count INTEGER NOT NULL DEFAULT 0,
    ocr_text TEXT,
    ocr_source TEXT,
    force_fallback BOOLEAN NOT NULL DEFAULT false,
    content_hash TEXT,
    from_cache BOOLEAN NOT NULL DEFAULT false,
    error_message TEXT,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS facts (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    fact_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE pages ADD COLUMN IF NOT EXISTS ocr_source TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS force_fallback BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS from_cache BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS facts_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE batches ADD COLUMN IF NOT EXISTS facts_status TEXT NOT NULL DEFAULT 'pending';

CREATE INDEX IF NOT EXISTS idx_pages_status ON pages (status, id);
CREATE INDEX IF NOT EXISTS idx_documents_batch ON documents (batch_id);
CREATE INDEX IF NOT EXISTS idx_pages_content_hash ON pages (content_hash) WHERE status = 'done';
CREATE INDEX IF NOT EXISTS idx_facts_batch ON facts (batch_id);
"""


def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)


if __name__ == "__main__":
    main()
