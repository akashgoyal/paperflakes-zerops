import os
import shutil
import urllib.request
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import db, ocr, worker

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/var/www/data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR = Path(__file__).parent / "static"

ALLOWED_URL_HOSTS = {"arxiv.org", "export.arxiv.org"}
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024

# Trial limit: only the first page of any document is actually OCR'd; the
# rest are recorded as 'skipped'. Raise (or remove) once ready for full runs.
MAX_PAGES_PER_DOCUMENT = 1


@asynccontextmanager
async def lifespan(app: FastAPI):
    worker.start_background_thread()
    yield


app = FastAPI(lifespan=lifespan)


class DocumentFromUrl(BaseModel):
    url: str
    title: str | None = None


def _register_document(batch_id: int, filename: str, dest_path: Path, title: str | None = None) -> dict:
    try:
        num_pages = ocr.count_pages(str(dest_path))
    except Exception:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="could not read PDF")

    if num_pages == 0:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="PDF has no pages")

    pages_to_process = min(num_pages, MAX_PAGES_PER_DOCUMENT)
    document_id = db.add_document(batch_id, filename, str(dest_path), num_pages, pages_to_process, title)
    return {"document_id": document_id, "num_pages": num_pages}


def _download_pdf(url: str, dest_path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "batch-ocr/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        total = 0
        with dest_path.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ValueError("PDF exceeds size limit")
                out.write(chunk)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/status")
def status():
    try:
        db.ping()
        db_ok = True
    except Exception:
        db_ok = False
    return JSONResponse(
        {"ok": db_ok, "model_ready": ocr.is_ready()},
        status_code=200 if db_ok else 503,
    )


@app.post("/api/batches")
def create_batch():
    return {"batch_id": db.create_batch()}


@app.post("/api/batches/{batch_id}/documents")
def upload_document(batch_id: int, file: UploadFile = File(...)):
    if not db.batch_exists(batch_id):
        raise HTTPException(status_code=404, detail="batch not found")

    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only .pdf files are accepted")

    batch_dir = UPLOAD_DIR / str(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    dest_path = batch_dir / f"{uuid.uuid4().hex}_{filename}"
    with dest_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    return _register_document(batch_id, filename, dest_path)


@app.post("/api/batches/{batch_id}/documents-from-url")
def add_document_from_url(batch_id: int, payload: DocumentFromUrl):
    if not db.batch_exists(batch_id):
        raise HTTPException(status_code=404, detail="batch not found")

    url = payload.url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_URL_HOSTS:
        raise HTTPException(status_code=400, detail="only https://arxiv.org PDF URLs are accepted")

    filename = (parsed.path.rstrip("/").rsplit("/", 1)[-1] or "paper") + ".pdf"
    filename = filename.replace(".pdf.pdf", ".pdf")

    batch_dir = UPLOAD_DIR / str(batch_id)
    batch_dir.mkdir(parents=True, exist_ok=True)
    dest_path = batch_dir / f"{uuid.uuid4().hex}_{filename}"
    try:
        _download_pdf(url, dest_path)
    except Exception:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="could not download PDF")

    return _register_document(batch_id, filename, dest_path, title=payload.title)


@app.get("/api/batches/{batch_id}")
def batch_status(batch_id: int):
    batch = db.get_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return batch


@app.get("/api/documents/{document_id}")
def document_detail(document_id: int):
    document = db.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    document["pages"] = db.get_pages(document_id)
    return document
