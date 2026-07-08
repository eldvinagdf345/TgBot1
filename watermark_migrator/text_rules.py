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
    original_name: str | None,
    terms: list[str],
    message_id: int,
    replacement: str = "Prime Sector",
    force_ext: str | None = None,
) -> str:
    """
    force_ext should be set (e.g. "mp4") only when the file's actual bytes were
    re-encoded into that container by us - otherwise the extension is taken
    from original_name so passed-through files (photos, voice, documents,
    untouched videos) keep a name that matches their real format.
    """
    if force_ext:
        ext = force_ext.lstrip(".")
    elif original_name and "." in original_name:
        ext = original_name.rsplit(".", 1)[-1]
    else:
        ext = None

    if contains_brand_term(original_name, terms):
        base = replacement
    elif original_name:
        base = original_name.rsplit(".", 1)[0] if "." in original_name else original_name
    else:
        base = f"file_{message_id}"

    return f"{base}.{ext}" if ext else base
