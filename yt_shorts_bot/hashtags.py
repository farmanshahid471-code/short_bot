"""Title, hashtag, description, transcript, and sidecar helpers.

Hashtags stay user-typed. When smart titles are on, the visible title is
rewritten from the source title plus spoken/description words so it is not
a copy of the original.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from .config import ENABLE_SMART_TITLES, TITLE_PREFIX, logger

STOPWORDS = set(
    """a about after all also am an and any are as at be because been before being
    between both but by can could did do does doing down during each few for from
    further had has have having he her here hers herself him himself his how i if
    in into is it its itself just me more most my myself no nor not now of off on
    once only or other our ours ourselves out over own same she should so some
    such than that the their theirs them themselves then there these they this
    those through to too under until up very was we were what when where which
    while who whom why will with you your yours yourself yourselves youtube video
    watch official channel shorts subscribe clip clips like share comment""".split()
)


def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def _is_stop(word: str) -> bool:
    return word in STOPWORDS or len(word) < 3


def _source_hashtags(*texts: str) -> list[str]:
    """Compatibility helper; source hashtags are not published automatically."""
    output: list[str] = []
    for text in texts:
        for tag in re.findall(r"#([A-Za-z0-9_]{2,})", text or ""):
            tag = tag.lower()
            if tag not in output:
                output.append(tag)
    return output


def extract_keywords(*texts: str, top_n: int = 14) -> list[str]:
    """Compatibility helper for callers that want local keyword analysis."""
    counts: Counter = Counter()
    capitals: Counter = Counter()
    for index, text in enumerate(texts):
        if not text:
            continue
        weight = 3 if index < 4 else 1
        for word in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", text):
            normalized = _norm(word)
            if _is_stop(normalized):
                continue
            counts[normalized] += weight
            if word[0].isupper():
                capitals[normalized] += 1
    return sorted(
        counts,
        key=lambda word: counts[word] + (2.0 if capitals[word] else 0.0),
        reverse=True,
    )[:top_n]


_JUNK_TITLE = re.compile(
    r"\b(official\s+(?:music\s+)?(?:video|audio)|lyric(?:s)?(?:\s+video)?|"
    r"full\s+video|hd|4k|youtube\s+shorts?|#shorts|subscribe)\b",
    re.IGNORECASE,
)
_SPOKEN_FILLER = {
    "um",
    "uh",
    "ah",
    "er",
    "like",
    "yeah",
    "okay",
    "ok",
    "so",
    "well",
}
_TITLE_HOOKS = (
    "Wait for this: {topic}",
    "This {topic} moment hits different",
    "When {topic} actually happens",
    "{topic} but nobody expected this",
    "The {topic} scene everyone skipped",
    "Why {topic} still goes hard",
    "Nobody talks about this {topic}",
    "{topic} got out of hand",
)


def _split_tags(value: str) -> list[str]:
    value = (value or "").replace("#", " ").replace(",", " ")
    return [tag.strip() for tag in value.split() if tag.strip()]


def _smart_titles_enabled(smart_titles: Optional[bool]) -> bool:
    return ENABLE_SMART_TITLES if smart_titles is None else bool(smart_titles)


def _clean_source_title(original: str) -> str:
    text = re.sub(r"#\w+", " ", original or "")
    text = re.sub(r"[@\[\](){}]", " ", text)
    text = _JUNK_TITLE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" -_|•·:.")
    return text


def _normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _looks_english(text: str) -> bool:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return True
    ascii_letters = [char for char in letters if char.isascii()]
    return (len(ascii_letters) / len(letters)) >= 0.7


def _topic_phrase(clean_title: str, keywords: list[str], max_words: int = 6) -> str:
    words = [word for word in re.findall(r"[A-Za-z0-9']+", clean_title) if word]
    if words:
        return " ".join(words[:max_words])
    if keywords:
        return " ".join(keywords[:3]).title()
    return "this clip"


def _spoken_hook(transcript: str, max_words: int = 9) -> str:
    text = re.sub(r"\s+", " ", transcript or "").strip()
    if not text:
        return ""
    sentence = re.split(r"[.!?]\s+", text, maxsplit=1)[0]
    words = [
        word
        for word in re.findall(r"[A-Za-z0-9']+", sentence)
        if word.casefold() not in _SPOKEN_FILLER
    ]
    if len(words) < 3:
        return ""
    hook = " ".join(words[:max_words])
    return hook[:1].upper() + hook[1:] if hook else ""


def invent_smart_title(
    original_title: str,
    transcript_text: str = "",
    info: Optional[dict[str, Any]] = None,
) -> str:
    """Rewrite a source title using the original words plus video/transcript cues."""
    info = info or {}
    clean = _clean_source_title(original_title or str(info.get("title") or ""))
    description = str(info.get("description") or "")
    tag_text = " ".join(str(tag) for tag in (info.get("tags") or [])[:8])
    keywords = extract_keywords(clean, transcript_text, description, tag_text, top_n=8)
    topic = _topic_phrase(clean, keywords)
    spoken = _spoken_hook(transcript_text) or _spoken_hook(description)
    original_key = _normalize_title(clean)

    candidates: list[str] = []
    if spoken and _normalize_title(spoken) != original_key:
        candidates.append(spoken)
        if topic and topic.casefold() not in spoken.casefold():
            candidates.append(f"{spoken} — {topic}")
    if _looks_english(topic):
        hook = _TITLE_HOOKS[sum(ord(char) for char in original_key) % len(_TITLE_HOOKS)]
        candidates.append(hook.format(topic=topic))
    if clean:
        candidates.append(f"{clean}...")
        candidates.append(f"Watch this: {clean}")

    for candidate in candidates:
        rewritten = re.sub(r"\s+", " ", candidate).strip(" -_|")
        if rewritten and _normalize_title(rewritten) != original_key:
            return rewritten
    return f"This {topic} clip" if topic else "This clip hits different"


def build_hashtags(
    info: Optional[dict[str, Any]] = None,
    transcript_text: str = "",
    extra_hashtags: str = "",
    top_n: int = 12,
    smart_titles: Optional[bool] = None,
    title_hashtags: str = "",
) -> list[str]:
    """Return only explicit user hashtags; content is never inferred."""
    del info, transcript_text, top_n, smart_titles
    user_tags: list[str] = []
    for tag in _split_tags(title_hashtags or extra_hashtags):
        normalized = _norm(tag)
        if normalized and normalized not in user_tags:
            user_tags.append(normalized)
    logger.debug("User-controlled hashtags: %s", user_tags)
    return user_tags


def make_catchy_title(
    info: Optional[dict[str, Any]] = None,
    transcript_text: str = "",
    extra_hashtags: str = "",
    part_label: str = "",
    max_len: int = 100,
    title_prefix: Optional[str] = None,
    title_hashtags: str = "",
    smart_titles: Optional[bool] = None,
) -> str:
    """Build ``prefix + title + explicit hashtags`` within 100 chars.

    With smart titles on, the middle part is invented from the source title
    and video/transcript words. Hashtags are never invented.
    """
    del extra_hashtags
    info = info or {}
    original = str(info.get("title") or "")
    if _smart_titles_enabled(smart_titles):
        body = invent_smart_title(original, transcript_text, info)
    else:
        body = _clean_source_title(original)
        if len(body) > 60:
            body = body[:57].strip() + "..."

    raw_prefix = (
        title_prefix
        if title_prefix is not None
        else (info.get("title_prefix") or TITLE_PREFIX or "")
    )
    prefix = str(raw_prefix or "").strip()
    if prefix:
        prefix += " "
    if part_label:
        prefix = f"{prefix}{part_label} - "

    user_tags = [tag.lstrip("#") for tag in _split_tags(title_hashtags)]
    tags_text = " ".join("#" + tag for tag in user_tags)
    tags_part = (" " + tags_text) if tags_text else ""
    if len(prefix) + len(body) + len(tags_part) > max_len:
        available = max_len - len(prefix) - len(tags_part) - 1
        if available >= 10:
            body = body[: max(0, available - 1)].rstrip() + "…"
        else:
            available = max_len - len(prefix) - 1
            body = body[: max(0, available - 1)].rstrip() + "…"
            tags_part = ""
    result = f"{prefix}{body}{tags_part}".strip()
    return result if len(result) <= max_len else result[: max_len - 1].rstrip() + "…"


def make_description(
    original_title: str,
    original_url: str = "",
    hashtags: Optional[list[str]] = None,
) -> str:
    """Build a description without exposing the source URL or source hashtags."""
    del original_url
    tag_line = " ".join("#" + tag for tag in (hashtags or []))
    quoted = re.sub(r"#\w+", "", str(original_title or "")).strip()
    return (
        f"🎬 High-engagement highlight clip from: {quoted}\n"
        "💡 Subscribe for daily curated shorts & insights!\n\n"
        f"{tag_line}"
    )


def srt_to_text(srt_path) -> str:
    try:
        path = Path(srt_path)
        if not path.exists():
            return ""
        lines = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or "-->" in line or line.isdigit():
                continue
            lines.append(line)
        return " ".join(lines)
    except (OSError, TypeError):
        return ""


def save_metadata_sidecar(
    short_video_path,
    metadata: dict[str, Any],
    source_url: str = "",
    short_id: str = "",
    account: str = "",
) -> Optional[Path]:
    """Write the exact attempted upload metadata next to a finished video."""
    try:
        path = Path(short_video_path)
        if not path.exists():
            return None
        sidecar = path.with_suffix(".txt")
        lines = [
            "=== SHORT METADATA (exact upload attempt) ===",
            "",
            f"Account       : {account or 'default'}",
            f"Source URL    : {source_url}",
            f"YouTube Short : {short_id or '(not uploaded)'}",
            "",
            f"TITLE         : {metadata.get('title', '')}",
            "",
            "DESCRIPTION:",
            str(metadata.get("description", "")),
            "",
            "TAGS: " + ", ".join(metadata.get("tags", [])),
        ]
        sidecar.write_text("\n".join(lines), encoding="utf-8")
        logger.info("Saved metadata sidecar: %s", sidecar)
        return sidecar
    except (OSError, TypeError) as exc:
        logger.warning("Could not write metadata sidecar: %s", exc)
        return None
