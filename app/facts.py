import json
import os

from together import Together

MODEL_ID = os.environ.get("TOGETHER_MODEL", "google/gemma-4-31B-it")
MAX_TOKENS = 4096
REQUEST_TIMEOUT_SECONDS = 180.0
FACTS_PER_DOCUMENT = 3
MAX_INPUT_CHARS = 6000

DEFAULT_STYLE = "did_you_know"

STYLES = {
    "did_you_know": {
        "label": "Did You Know?",
        "icon": "💡",
        "instruction": (
            'write {n} short, surprising "Did you know?" facts a curious general reader '
            "(not a specialist) would enjoy. Each must be directly supported by the excerpt, "
            "1-2 sentences, and free of jargon dumps."
        ),
    },
    "key_takeaways": {
        "label": "Key Takeaway",
        "icon": "🔑",
        "instruction": (
            "write {n} key takeaways a busy reader needs to know. Each should be a concise, "
            "high-value insight directly supported by the excerpt, 1-2 sentences."
        ),
    },
    "contrarian_arguments": {
        "label": "Contrarian Take",
        "icon": "⚡",
        "instruction": (
            "identify {n} contrarian or counter-intuitive claims this excerpt makes against "
            "conventional wisdom or prior assumptions. Each should be 1-2 sentences, directly "
            "supported by the excerpt."
        ),
    },
    "actionable_data_points": {
        "label": "Data Point",
        "icon": "📊",
        "instruction": (
            "extract {n} concrete, actionable data points (numbers, results, benchmarks) from "
            "this excerpt that a practitioner could actually cite or use. Each should be 1-2 sentences."
        ),
    },
}

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = Together(api_key=os.environ["TOGETHER_API_KEY"], timeout=REQUEST_TIMEOUT_SECONDS)
    return _client


def _parse_facts(content: str) -> list[str]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        return [cleaned] if cleaned else []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [cleaned] if cleaned else []


def generate_facts(title: str, text: str, style: str = DEFAULT_STYLE) -> list[str]:
    style_def = STYLES.get(style, STYLES[DEFAULT_STYLE])
    instruction = style_def["instruction"].format(n=FACTS_PER_DOCUMENT)
    prompt = (
        f'Based on this excerpt from the paper "{title}", {instruction} '
        "Do not explain your reasoning, do not add commentary or numbering — "
        'respond with ONLY a JSON array of strings, e.g. ["item one", "item two"].\n\n'
        f"Excerpt:\n{text[:MAX_INPUT_CHARS]}"
    )
    response = _get_client().chat.completions.create(
        model=MODEL_ID,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=MAX_TOKENS,
    )
    content = (response.choices[0].message.content or "").strip()
    return _parse_facts(content)
