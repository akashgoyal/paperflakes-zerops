import base64
import hashlib
import io
import os

import pypdfium2 as pdfium
from together import Together

from .util import call_with_hard_timeout

MODEL_ID = os.environ.get("TOGETHER_MODEL", "google/gemma-4-31B-it")
# 200 DPI, per common vision-model page-rendering guidance (scale = dpi / 72).
RENDER_SCALE = 200 / 72
PROMPT = (
    "Transcribe all visible text from this document page exactly as written, "
    "in reading order. Do not explain your reasoning, do not second-guess "
    "yourself, and do not add commentary — output only the final transcribed text."
)

# gemma-4-31B-it is a reasoning model: it can spend thousands of tokens on
# chain-of-thought before writing the final answer, so it needs a generous
# max_tokens (else it gets cut off mid-thought with empty content) and a
# client timeout well beyond the SDK default (else a slow-but-healthy
# generation looks like a network failure).
MAX_TOKENS = 8192
REQUEST_TIMEOUT_SECONDS = 180.0

_client = None


def is_ready() -> bool:
    return bool(os.environ.get("TOGETHER_API_KEY"))


def _get_client():
    global _client
    if _client is None:
        _client = Together(api_key=os.environ["TOGETHER_API_KEY"], timeout=REQUEST_TIMEOUT_SECONDS)
    return _client


def count_pages(pdf_path: str) -> int:
    return len(pdfium.PdfDocument(pdf_path))


def render_page(pdf_path: str, page_index: int):
    pdf = pdfium.PdfDocument(pdf_path)
    page = pdf[page_index]
    return page.render(scale=RENDER_SCALE).to_pil().convert("RGB")


def _to_png_bytes(pil_image) -> bytes:
    buffer = io.BytesIO()
    pil_image.save(buffer, format="PNG")
    return buffer.getvalue()


def hash_image(pil_image) -> str:
    """Content hash of the rendered page — identical pages (same PDF reprocessed,
    or the same page across documents) hash identically, so callers can skip OCR."""
    return hashlib.sha256(_to_png_bytes(pil_image)).hexdigest()


def _image_to_data_url(pil_image) -> str:
    encoded = base64.b64encode(_to_png_bytes(pil_image)).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def ocr_image(pil_image) -> str:
    def _call():
        return _get_client().chat.completions.create(
            model=MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": PROMPT},
                        {"type": "image_url", "image_url": {"url": _image_to_data_url(pil_image)}},
                    ],
                }
            ],
            max_tokens=MAX_TOKENS,
        )

    response = call_with_hard_timeout(_call, REQUEST_TIMEOUT_SECONDS)
    return (response.choices[0].message.content or "").strip()
