import re


def load_brand_terms(path: str) -> list[str]:
    terms = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                terms.append(line)
    return terms


def _term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term.strip())
    # tolerate variable whitespace where the term itself has spaces
    escaped = escaped.replace(r"\ ", r"\s+")
    return re.compile(escaped, re.IGNORECASE)


def contains_brand_term(text: str | None, terms: list[str]) -> bool:
    if not text:
        return False
    return any(_term_pattern(term).search(text) for term in terms)


def sanitize_text(text: str | None, terms: list[str]) -> str:
    """Strip any occurrence of the configured brand terms, collapsing the
    whitespace/blank lines that removal leaves behind."""
    if not text:
        return text or ""
    result = text
    for term in terms:
        result = _term_pattern(term).sub("", result)
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def sanitized_filename(
    original_name: str | None, terms: list[str], message_id: int, replacement: str = "Prime Sector"
) -> str:
    if contains_brand_term(original_name, terms):
        return f"{replacement}.mp4"
    if original_name:
        return original_name
    return f"video_{message_id}.mp4"
