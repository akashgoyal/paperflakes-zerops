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
    db.refresh_document_progress(page["document_id"])
    # Runs regardless of this page's outcome — a failed OCR page just has no text,
    # so fact generation no-ops for it. Triggered per-page (not per-document) so
    # each page's cards can appear independently once multi-page runs are enabled.
    _generate_page_facts(page["id"])


def _generate_page_facts(page_id: int) -> None:
    if not db.claim_page_facts(page_id):
        return  # already generated, generating, or nothing to do

    try:
        page = db.get_page_for_facts(page_id)
        if not page or not page["ocr_text"]:
            db.set_page_facts_status(page_id, "done")
            return

        label = page["title"] or page["filename"]
        already_done = db.get_existing_fact_categories(page_id)

        for category in facts.CATEGORY_ORDER:
            if category in already_done:
                continue  # survived a crash from a previous partial run — don't redo it
            try:
                cached_text = db.find_cached_fact(page["content_hash"], category)
                if cached_text is not None:
                    fact_text = cached_text
                else:
                    fact_text = facts.generate_fact_for_category(label, page["ocr_text"], category)
                    db.cache_fact(page["content_hash"], category, fact_text)
                # Saved immediately — visible on the very next poll rather than
                # waiting for all four categories to finish.
                db.save_fact(page["batch_id"], page["document_id"], page_id, category, fact_text)
            except Exception:
                traceback.print_exc()
                continue  # this category failed; still attempt the rest

        db.set_page_facts_status(page_id, "done")
    except Exception:
        traceback.print_exc()
        db.set_page_facts_status(page_id, "error")


def run_forever() -> None:
    recovered = db.recover_orphaned_pages()
    if recovered:
        print(f"Requeued {recovered} page(s) orphaned by a previous crash.")

    for page_id in db.recover_orphaned_page_facts():
        _generate_page_facts(page_id)

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
