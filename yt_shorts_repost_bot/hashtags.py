"""
hashtags.py - Free, local, content-aware title & hashtag generation for Shorts.

Uses ONLY what the bot already has: the source video's title, description,
tags, channel name, category, plus the free CPU transcription (faster-whisper).
No paid AI APIs. Gives Shorts reach hashtags like:
  #simpsons #bart #homer #tvshow #shorts #viral #fyp #trending
"""
import re
from collections import Counter
from pathlib import Path
from typing import Dict, Any, List, Optional

from .config import (
    ENABLE_SMART_TITLES,
    MAX_TITLE_HASHTAGS,
    REACH_HASHTAGS,
    EXTRA_HASHTAGS,
    TITLE_PREFIX,
    logger,
)

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

# Generic topic -> hashtag for common YouTube categories
CATEGORY_TAGS = {
    "gaming": "gaming",
    "entertainment": "entertainment",
    "comedy": "comedy",
    "education": "education",
    "music": "music",
    "sports": "sports",
    "film & animation": "animation",
    "people & blogs": "vlog",
    "news & politics": "news",
    "howto & style": "howto",
    "science & technology": "tech",
    "travel & events": "travel",
    "autos & vehicles": "cars",
    "pets & animals": "animals",
    "movies": "movies",
    "tv shows": "tvshow",
    "tvshow": "tvshow",
}

# Multiword tags: join words so the hashtag stays valid (#bartSimpson)
def _norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def _is_stop(w: str) -> bool:
    return w in STOPWORDS or len(w) < 3


def _source_hashtags(*texts: str) -> List[str]:
    """Pulls existing #hashtags out of text (title/description)."""
    out = []
    for text in texts:
        for t in re.findall(r"#([A-Za-z0-9_]{2,})", text or ""):
            t = t.lower()
            if t not in out:
                out.append(t)
    return out


def extract_keywords(*texts: str, top_n: int = 14) -> List[str]:
    """
    Frequency-based keyword extraction. Title/description/tags/channel weigh 3x
    more than transcript. Capitalized words (names like Bart/Homer) get a boost.
    """
    counts: Counter = Counter()
    caps: Counter = Counter()
    for i, text in enumerate(texts):
        if not text:
            continue
        weight = 3 if i < 4 else 1
        for w in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", text):
            lw = _norm(w)
            if _is_stop(lw):
                continue
            counts[lw] += weight
            if w[0].isupper():
                caps[lw] += 1

    def score(w: str) -> float:
        return counts[w] + (2.0 if caps[w] >= 1 else 0.0)

    return sorted(counts, key=score, reverse=True)[:top_n]


def _split_tags(s: str) -> List[str]:
    s = (s or "").replace("#", " ").replace(",", " ")
    return [t.strip() for t in s.split() if t.strip()]


def build_hashtags(
    info: Optional[Dict[str, Any]] = None,
    transcript_text: str = "",
    extra_hashtags: str = "",
    top_n: int = 12,
    smart_titles: Optional[bool] = None,
    title_hashtags: str = "",
) -> List[str]:
    """
    Builds the hashtag list for the Short.
    ONLY the user's own hashtags (from the Title Hashtags setting) are used.
    The bot NEVER auto-generates hashtags from the video content, channel,
    description or transcript. No reach tags, no extra tags.
    """
    user_tags = []
    for t in _split_tags(title_hashtags or extra_hashtags):
        n = _norm(t)
        if n and n not in user_tags:
            user_tags.append(n)
    logger.debug(f"User hashtags only: {user_tags}")
    return user_tags


def make_catchy_title(
    info: Optional[Dict[str, Any]] = None,
    transcript_text: str = "",
    extra_hashtags: str = "",
    part_label: str = "",
    max_len: int = 100,
    title_prefix: Optional[str] = None,
    title_hashtags: str = "",
    smart_titles: Optional[bool] = None,
) -> str:
    """
    Builds the Short title:
      {prefix} {video title} {#hashtags the user wrote in Title Hashtags}
    Smart titles only affect the DESCRIPTION tags, not the title.
    """
    info = info or {}
    original = info.get("title") or ""
    # Remove the source title's OWN hashtags entirely (#word + word),
    # then strip other symbols. Only the user's Title Hashtags may appear.
    clean = re.sub(r"#\w+", "", original)
    clean = re.sub(r"[@\[\](){}]", "", clean).strip()
    if len(clean) > 60:
        clean = clean[:57].strip() + "..."

    # Explicitly-empty prefix stays empty (no emoji fallback). Fallback only
    # when NOTHING was provided at all (None).
    raw_prefix = title_prefix if title_prefix is not None else (info.get("title_prefix") or TITLE_PREFIX or "")
    prefix = str(raw_prefix or "").strip()
    if prefix and not prefix.endswith(" "):
        prefix += " "
    if part_label:
        prefix = f"{prefix}{part_label} - "

    # User's own Title Hashtags - exactly as many as they wrote
    user_tags = [t.lstrip("#") for t in _split_tags(title_hashtags) if t.strip()]
    htxt = " ".join("#" + t for t in user_tags)

    # Build the title as: {prefix}{video title}{ #hashtags}
    # If it is too long, shorten the VIDEO TITLE part first - the user's
    # hashtags are the important part and must always survive.
    tags_part = (" " + htxt) if htxt else ""
    if len(prefix) + len(clean) + len(tags_part) > max_len:
        avail = max_len - len(prefix) - len(tags_part) - 1
        if avail >= 10:
            clean = clean[: max(0, avail - 1)].rstrip() + "…"
        else:
            # video title is huge even without hashtags - keep prefix, drop tags
            avail2 = max_len - len(prefix) - 1
            clean = clean[: max(0, avail2 - 1)].rstrip() + "…"
            tags_part = ""
    result = f"{prefix}{clean}{tags_part}".strip()
    if len(result) > max_len:
        result = result[: max_len - 1].rstrip() + "…"
    return result


def make_description(
    original_title: str,
    original_url: str = "",
    hashtags: Optional[List[str]] = None,
) -> str:
    """Engaging description with the full hashtag block (no source URL)."""
    tag_line = " ".join("#" + t for t in (hashtags or []))
    # Quote the source title WITHOUT its own hashtags (only the user's tags appear)
    quoted = re.sub(r"#\w+", "", str(original_title or "")).strip()
    desc = (
        f"🎬 High-engagement highlight clip from: {quoted}\n"
        f"💡 Subscribe for daily curated shorts & insights!\n\n"
        f"{tag_line}"
    )
    return desc


def srt_to_text(srt_path) -> str:
    """Extracts the spoken words from a generated .srt file (strips indexes/timestamps)."""
    try:
        p = Path(srt_path)
        if not p.exists():
            return ""
        lines = []
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or "-->" in line or line.isdigit():
                continue
            lines.append(line)
        return " ".join(lines)
    except Exception:
        return ""


def save_metadata_sidecar(
    short_video_path,
    metadata: Dict[str, Any],
    source_url: str = "",
    short_id: str = "",
    account: str = "",
) -> Optional[Path]:
    """
    Writes a .txt file NEXT TO a finished Short with the generated title,
    description, tags and source info - so you can review what the bot WOULD
    post (useful in dry-run mode where nothing is uploaded for real).
    Returns the sidecar path, or None.
    """
    try:
        p = Path(short_video_path)
        if not p.exists():
            return None
        sidecar = p.with_suffix(".txt")
        lines = [
            "=== SHORT METADATA (what would be uploaded to YouTube) ===",
            "",
            f"Account       : {account or 'default'}",
            f"Source URL    : {source_url}",
            f"YouTube Short : {short_id or '(not uploaded - dry run)'}",
            "",
            f"TITLE         : {metadata.get('title', '')}",
            "",
            "DESCRIPTION:",
            metadata.get("description", ""),
            "",
            "TAGS: " + ", ".join(metadata.get("tags", [])),
            "",
            "HASHTAGS (in title+description): " + " ".join(
                "#" + t for t in metadata.get("tags", []) if t.lower() in metadata.get("description", "").lower()
            ),
        ]
        sidecar.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"📝 Saved metadata sidecar: {sidecar}")
        return sidecar
    except Exception as e:
        logger.warning(f"Could not write metadata sidecar: {e}")
        return None
