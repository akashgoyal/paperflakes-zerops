import json
import os

from together import Together

MODEL_ID = os.environ.get("TOGETHER_MODEL", "google/gemma-4-31B-it")
MAX_TOKENS = 4096
REQUEST_TIMEOUT_SECONDS = 180.0
MAX_INPUT_CHARS = 6000

DEFAULT_CATEGORY = "did_you_know"

# One fact per category per document — each note tags itself with the category
# it came from, rather than the whole batch picking a single style upfront.
CATEGORY_ORDER = ["did_you_know", "key_takeaways", "contrarian_arguments", "actionable_data_points"]

CATEGORIES = {
    "did_you_know": {
        "label": "Did You Know?",
        "icon": "💡",
        "ask": 'A short, surprising "did you know?" fact a curious general reader would enjoy.',
    },
    "key_takeaways": {
        "label": "Key Takeaway",
        "icon": "🔑",
        "ask": "A concise, high-value key takeaway a busy reader needs to know.",
    },
    "contrarian_arguments": {
        "label": "Contrarian Take",
        "icon": "⚡",
        "ask": "A contrarian or counter-intuitive claim this excerpt makes against conventional wisdom.",
    },
    "actionable_data_points": {
        "label": "Data Point",
        "icon": "📊",
        "ask": "One concrete, actionable data point (a number, result, or benchmark) a practitioner could cite.",
    },
}

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Together(api_key=os.environ["TOGETHER_API_KEY"], timeout=REQUEST_TIMEOUT_SECONDS)
    return _client


def _parse_categorized_facts(content: str) -> list[dict]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        parsed = None

    results = []
    if isinstance(parsed, dict):
        for category in CATEGORY_ORDER:
            value = parsed.get(category)
            if value and str(value).strip():
                results.append({"category": category, "text": str(value).strip()})

    if not results and cleaned:
        # Model didn't follow the schema — surface the raw text rather than nothing.
        results.append({"category": DEFAULT_CATEGORY, "text": cleaned})
    return results


def generate_facts(title: str, text: str) -> list[dict]:
    """Returns up to one {category, text} item per category in CATEGORY_ORDER."""
    requests_block = "\n".join(f'- "{key}": {CATEGORIES[key]["ask"]}' for key in CATEGORY_ORDER)
    prompt = (
        f'Based on this excerpt from the paper "{title}", produce exactly one item for each of '
        f"these categories:\n{requests_block}\n\n"
        "Each item must be 1-2 sentences, directly supported by the excerpt, and free of jargon dumps. "
        "Do not explain your reasoning, do not add commentary — "
        "respond with ONLY a JSON object whose keys are exactly "
        f'{json.dumps(CATEGORY_ORDER)} and whose values are the corresponding text.\n\n'
        f"Excerpt:\n{text[:MAX_INPUT_CHARS]}"
    )
    response = _get_client().chat.completions.create(
        model=MODEL_ID,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=MAX_TOKENS,
    )
    content = (response.choices[0].message.content or "").strip()
    return _parse_categorized_facts(content)
