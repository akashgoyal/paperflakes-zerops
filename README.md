# 📄 PaperFlakes-zerops

Turn dense PDFs into shareable, bite-sized facts — powered by Zerops.

**Live demo:** https://app-2c11-8000.prg1.zerops.app

PaperFlakes takes PDFs — pick from a curated list of classic ML papers or
upload your own — OCRs them, and turns the extracted text into shareable
"sticky note" insight cards across four categories, which you can filter,
download as images, or share straight to X/Twitter.

## Features

- **Pick a paper or bring your own** — choose from a curated list of
  well-known ML papers (Transformer, BERT, GANs, ResNet, ViT, Adam,
  diffusion models, GPT-3) or upload up to 100 PDFs of your own.
- **Batch processing with live progress** — every document in a batch is
  tracked independently (queued → processing → done/error) in a
  live-updating status table.
- **OCR via a vision-language model** — pages are rendered to images and
  sent one page at a time (batch size of 1) to `google/gemma-4-31B-it` on
  Together AI.
- **Four insight categories per document** — Did You Know?, Key Takeaways,
  Contrarian Arguments, and Actionable Data Points are each generated as a
  separate, focused LLM call rather than one combined call, so a category's
  card appears in the UI the moment it's ready instead of all four waiting
  on the slowest one.
- **Two-layer caching** — both the OCR'd text and each category's fact are
  cached by a hash of the rendered page image. Reprocessing a page that's
  been seen before (same PDF, same page) skips the LLM entirely.
- **Filterable insights panel** — toggle categories on/off and narrow the
  view to a single paper.
- **Download & share** — save any card as a PNG (canvas-rendered to match
  the on-screen design), export every visible card as one combined image,
  or share to X with the paper's title, source link, and attribution
  pre-filled.
- **Crash-safe processing** — a worker restart recovers any page or fact
  generation that was interrupted mid-flight instead of leaving it stuck.

## Design

PaperFlakes is intentionally a single Python service, not a microservice
fleet — a background thread inside the same process as the web server
processes work sequentially, one page at a time.

```
Browser ──HTTP──▶ FastAPI (app.main)
                     │
                     ├─ serves the UI (app/static/index.html) and the
                     │  batch / document / facts API
                     │
                     └─ on startup, spawns a background worker thread
                        (app.worker) that loops:
                          1. claim the oldest queued page
                          2. render it to an image (pypdfium2)
                          3. hash the image → check the OCR cache
                          4. OCR via Together AI if not cached
                          5. for each of 4 categories:
                             check the facts cache, else generate via
                             Together AI — save immediately either way
                          6. move to the next page
```

Everything the worker reads and writes lives in PostgreSQL — batches,
documents, pages, facts, and two content-hash-keyed cache tables.

Why one process instead of a queue plus a separate worker service? The
requirement was "process pages one at a time." A single in-process thread
gives that for free, with no message broker, no distributed state, and no
risk of two workers racing on the same page — `maxContainers: 1` on the
Zerops service guarantees there's never a second instance to race with.

**Trial mode:** only page 1 of each document is actually OCR'd (the rest
are marked `skipped`) — see `MAX_PAGES_PER_DOCUMENT` in `app/main.py`.
This was a deliberate scope limit during development; the schema, worker,
and caching are already page-scoped, so raising or removing it is a
small, contained change.

### Data model

| Table | Purpose |
|---|---|
| `batches` | one row per "process these documents together" action |
| `documents` | one row per PDF (uploaded or fetched from arXiv) |
| `pages` | one row per page — OCR status, extracted text, content hash |
| `facts` | one row per generated insight card, tagged with category + source page |
| `page_facts` | cache: `(content_hash, category) → fact text`, reused across any page with identical rendered content |

### Known limitations

- Only page 1 of each PDF is processed today (see Trial mode above).
- Processing is intentionally single-threaded/sequential rather than a
  distributed queue + worker pool — correct for the "one page at a time"
  requirement, but it doesn't scale horizontally as-is.
- `google/gemma-4-31B-it` is a reasoning model and can be slow (tens of
  seconds per category); if a single category's call fails, the UI just
  omits that card rather than blocking the other three.

## What's used from Zerops

- **Python runtime service** (`app`, Ubuntu base) — runs the FastAPI web
  server and the background worker in one container. `maxContainers: 1`
  is set deliberately so processing stays strictly sequential.
- **Managed PostgreSQL** (`db`, `postgresql:single@18`) — the only
  persistent store, wired into the app via `${db_*}` cross-service
  references in `zerops.yaml` rather than hardcoded credentials.
- **zerops.app subdomain** — the public HTTPS URL, enabled automatically
  on first deploy.
- **Git-push deploy + GitHub Actions integration** — pushing to `main`
  triggers `.github/workflows/zerops.yml`, which runs `zcli push` against
  this service; Zerops builds and deploys straight from the pushed
  commit. Set up via `zerops_workflow action="git-push-setup"` and
  `action="build-integration"`.
- **Secrets** — `TOGETHER_API_KEY` is stored as a Zerops service secret,
  never committed, and read from the environment at runtime.
- **readinessCheck / healthCheck** — both point at `GET /status`, which
  checks live DB connectivity, so a container only goes live (and only
  receives traffic on deploy) once it can actually reach Postgres.

## How to use it

1. Open the [live app](https://app-2c11-8000.prg1.zerops.app).
2. Either:
   - check one or more papers under **"Try it on papers"** and click
     **Process batch**, or
   - choose PDF files under **"Batch upload"** (up to 100) and click
     **Upload & process**.
3. Watch the **Processing status** table update as each document is OCR'd.
4. Insight cards appear in the **Insights** panel as soon as each category
   finishes — no need to wait for the whole batch.
5. Use the category chips and paper dropdown above the panel to filter
   what's shown.
6. On any card: **⬇ Save** downloads it as a PNG, **𝕏 Share** opens a
   pre-filled tweet. **⬇ Download all** (top right) exports every
   currently-visible card as one combined image.

## Running your own copy

This repo is a self-contained Zerops service: `zerops.yaml` defines the
build/run pipeline, and `migrate.py` sets up the schema idempotently on
every deploy.

1. Create a Zerops project with a Python runtime service and a
   `postgresql:single` managed service (hostname `db`).
2. Get a [Together AI](https://www.together.ai/) API key and set it as
   `TOGETHER_API_KEY` — a secret on the runtime service.
3. `zerops.yaml` already wires `DATABASE_URL` from `${db_user}` /
   `${db_password}` / `${db_hostname}` / `${db_port}` / `${db_dbName}`.
4. `git push` — the included GitHub Actions workflow deploys automatically
   once `ZEROPS_TOKEN` and `ZEROPS_SERVICE_ID` are set as repo secrets
   (or deploy directly with `zcli push` / the Zerops MCP tools).

## Tech stack

- **Backend:** Python, FastAPI, psycopg (raw SQL, no ORM)
- **OCR + insight generation:** [Together AI](https://www.together.ai/)
  running `google/gemma-4-31B-it`
- **PDF rendering:** pypdfium2
- **Database:** PostgreSQL
- **Frontend:** one static HTML file — vanilla JS, no framework, no build
  step
- **Infra:** Zerops (runtime service + managed Postgres + git-push CI/CD)

## API reference

| Endpoint | Purpose |
|---|---|
| `GET /` | the UI |
| `GET /status` | health check (DB connectivity) |
| `POST /api/batches` | create a batch |
| `POST /api/batches/{id}/documents` | upload a PDF into a batch |
| `POST /api/batches/{id}/documents-from-url` | fetch a PDF from arxiv.org into a batch |
| `GET /api/batches/{id}` | batch status: documents + generated facts |
| `GET /api/documents/{id}` | a single document's status + per-page detail |
