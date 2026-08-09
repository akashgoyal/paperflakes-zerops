import os

from together import Together

MODEL_ID = os.environ.get("TOGETHER_MODEL", "google/gemma-4-31B-it")
MAX_TOKENS = 4096
REQUEST_TIMEOUT_SECONDS = 180.0
MAX_INPUT_CHARS = 6000

# One focused call per category (rather than one combined call asking for all four)
# so each card can be persisted and shown the moment it's ready, instead of the
# whole set waiting on the slowest category.
CATEGORY_ORDER = ["did_you_know", "key_takeaways", "contrarian_arguments", "actionable_data_points"]

CATEGORIES = {
    "did_you_know": {
        "label": "Did You Know?",
        "icon": "💡",
        "ask": 'a short, surprising "did you know?" fact a curious general reader would enjoy',
    },
    "key_takeaways": {
        "label": "Key Takeaway",
        "icon": "🔑",
        "ask": "a concise, high-value key takeaway a busy reader needs to know",
    },
    "contrarian_arguments": {
        "label": "Contrarian Take",
        "icon": "⚡",
        "ask": "a contrarian or counter-intuitive claim this excerpt makes against conventional wisdom",
    },
    "actionable_data_points": {
        "label": "Data Point",
        "icon": "📊",
        "ask": "one concrete, actionable data point (a number, result, or benchmark) a practitioner could cite",
    },
}

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Together(api_key=os.environ["TOGETHER_API_KEY"], timeout=REQUEST_TIMEOUT_SECONDS)
    return _client


def _clean(text: str) -> str:
    cleaned = text.strip()
    if len(cleaned) >= 2 and cleaned[0] in "\"'" and cleaned[-1] == cleaned[0]:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def generate_fact_for_category(title: str, text: str, category: str) -> str:
    ask = CATEGORIES.get(category, CATEGORIES["did_you_know"])["ask"]
    prompt = (
        f'Based on this excerpt from the paper "{title}", write {ask}. '
        "1-2 sentences, directly supported by the excerpt, free of jargon dumps. "
        "Do not explain your reasoning, do not add commentary, quotes, or a label — "
        "respond with ONLY the fact text itself.\n\n"
        f"Excerpt:\n{text[:MAX_INPUT_CHARS]}"
    )
    response = _get_client().chat.completions.create(
        model=MODEL_ID,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=MAX_TOKENS,
    )
    return _clean(response.choices[0].message.content or "")
