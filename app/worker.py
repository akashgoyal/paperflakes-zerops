import threading
import time
import traceback

from . import db, facts, ocr

POLL_INTERVAL_SECONDS = 1.0


def _process_one_page(page: dict) -> None:
    try:
        image = ocr.render_page(page["file_path"], page["page_number"] - 1)
        content_hash = ocr.hash_image(image)
        cached = db.find_cached_page(content_hash)
        if cached is not None:
            db.save_page_result(
                page["id"], cached["ocr_text"], cached["char_count"], cached["word_count"],
                content_hash, from_cache=True,
            )
        else:
            text = ocr.ocr_image(image)
            db.save_page_result(page["id"], text, len(text), len(text.split()), content_hash)
    except Exception as exc:
        traceback.print_exc()
        db.save_page_error(page["id"], str(exc))
    status = db.refresh_document_progress(page["document_id"])
    if status in ("done", "error"):
        _maybe_generate_document_facts(page["document_id"])


def _maybe_generate_document_facts(document_id: int) -> None:
    """Fires the moment THIS document finishes — independent of any other document
    in its batch, so each paper's cards can appear as soon as it's ready."""
    if not db.claim_document_facts(document_id):
        return  # already generated, generating, or errored

    try:
        document = db.get_document_with_text(document_id)
        if not document or not document["ocr_text"]:
            db.set_document_facts_status(document_id, "done")  # nothing to generate from
            return
        label = document["title"] or document["filename"]
        fact_texts = facts.generate_facts(label, document["ocr_text"], style=document["fact_style"])
        db.save_facts([(document["batch_id"], document_id, text) for text in fact_texts])
        db.set_document_facts_status(document_id, "done")
    except Exception:
        traceback.print_exc()
        db.set_document_facts_status(document_id, "error")


def run_forever() -> None:
    recovered = db.recover_orphaned_pages()
    if recovered:
        print(f"Requeued {recovered} page(s) orphaned by a previous crash.")

    for document_id in db.recover_orphaned_facts():
        _maybe_generate_document_facts(document_id)

    while True:
        page = db.fetch_next_queued_page()
        if page is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        _process_one_page(page)


def start_background_thread() -> threading.Thread:
    thread = threading.Thread(target=run_forever, daemon=True, name="ocr-worker")
    thread.start()
    return thread
