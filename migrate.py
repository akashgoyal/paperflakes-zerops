import os

import psycopg

DDL = """
CREATE TABLE IF NOT EXISTS batches (
    id SERIAL PRIMARY KEY,
    facts_status TEXT NOT NULL DEFAULT 'pending',
    fact_style TEXT NOT NULL DEFAULT 'did_you_know',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    title TEXT,
    source_url TEXT,
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
    facts_status TEXT NOT NULL DEFAULT 'pending',
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
    page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE,
    category TEXT NOT NULL DEFAULT 'did_you_know',
    fact_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cache layer: a fact for a given (rendered-page-content, category) pair, reusable
-- across any document/page that happens to render identical content. Mirrors the
-- pages.content_hash OCR cache one layer up.
CREATE TABLE IF NOT EXISTS page_facts (
    id SERIAL PRIMARY KEY,
    content_hash TEXT NOT NULL,
    category TEXT NOT NULL,
    fact_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (content_hash, category)
);

ALTER TABLE pages ADD COLUMN IF NOT EXISTS ocr_source TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS force_fallback BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS content_hash TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS from_cache BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS facts_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE documents ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE batches ADD COLUMN IF NOT EXISTS facts_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE batches ADD COLUMN IF NOT EXISTS fact_style TEXT NOT NULL DEFAULT 'did_you_know';
ALTER TABLE facts ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'did_you_know';
ALTER TABLE facts ADD COLUMN IF NOT EXISTS page_id INTEGER REFERENCES pages(id) ON DELETE CASCADE;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS facts_status TEXT NOT NULL DEFAULT 'pending';

CREATE INDEX IF NOT EXISTS idx_pages_status ON pages (status, id);
CREATE INDEX IF NOT EXISTS idx_documents_batch ON documents (batch_id);
CREATE INDEX IF NOT EXISTS idx_pages_content_hash ON pages (content_hash) WHERE status = 'done';
CREATE INDEX IF NOT EXISTS idx_facts_batch ON facts (batch_id);
CREATE INDEX IF NOT EXISTS idx_facts_page ON facts (page_id);
"""


def main() -> None:
    dsn = os.environ["DATABASE_URL"]
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)


if __name__ == "__main__":
    main()
