"""
TEST 2: Metadata generation - title, description, tags.
Verifies the user's hard requirements:
  * hashtags = ONLY what's in "Title Hashtags"; empty field = NO hashtags
  * title_prefix explicitly empty stays empty (no emoji fallback)
  * no source URL in description
  * smart titles only affects description
"""
import sys
sys.path.insert(0, "/home/user")
from yt_shorts_bot import uploader as up
from yt_shorts_bot.hashtags import build_hashtags, make_catchy_title, make_description

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

ORIG = "The Simpsons - Homer Greatest Mistakes"

print("\n=== 1. Hashtags: ONLY user's tags ===")
tags = build_hashtags(info={"title": ORIG, "tags": ["simpsons", "homer"]},
                      transcript_text="doh stupid sexy flanders",
                      extra_hashtags="", smart_titles=True,
                      title_hashtags="simpsons, homer, bart")
check("only 3 user tags", tags == ["simpsons", "homer", "bart"], str(tags))
check("no reach tags, no content tags", all(t not in tags for t in ["shorts", "viral", "fyp", "trending", "stupid", "sexy"]))

tags2 = build_hashtags(info={"title": ORIG}, transcript_text="doh",
                       extra_hashtags="", smart_titles=True, title_hashtags="")
check("empty title_hashtags = NO hashtags at all", tags2 == [], str(tags2))

tags3 = build_hashtags(info={"title": ORIG}, transcript_text="",
                       extra_hashtags="", smart_titles=True,
                       title_hashtags="#Simpsons, homer #BART")
check("hash symbols + commas cleaned", tags3 == ["simpsons", "homer", "bart"], str(tags3))

print("\n=== 2. Title prefix: empty stays empty ===")
t = make_catchy_title(info={"title": ORIG}, title_prefix="", title_hashtags="", smart_titles=False)
check("empty prefix -> no emoji, title only", t == ORIG, t)
t2 = make_catchy_title(info={"title": ORIG}, title_prefix=None, title_hashtags="", smart_titles=False)
check("None prefix -> fallback config ('' in this build)", t2 == ORIG, t2)
t3 = make_catchy_title(info={"title": ORIG}, title_prefix="🔥", title_hashtags="", smart_titles=False)
check("prefix 🔥 prepended", t3 == f"🔥 {ORIG}", t3)

print("\n=== 3. Title hashtags appended to title ===")
t4 = make_catchy_title(info={"title": ORIG}, title_prefix="", title_hashtags="simpsons, homer",
                       smart_titles=False)
check("tags in title", t4 == f"{ORIG} #simpsons #homer", t4)
t5 = make_catchy_title(info={"title": ORIG}, title_prefix="🔥", title_hashtags="simpsons",
                       smart_titles=False)
check("prefix + tags", t5 == f"🔥 {ORIG} #simpsons", t5)

long_title = "A" * 120
t6 = make_catchy_title(info={"title": long_title}, title_prefix="", title_hashtags="a, b, c, d, e, f, g, h", smart_titles=False)
check("title capped at 100 chars", len(t6) <= 100, f"len={len(t6)}")

print("\n=== 4. Description: no source URL, tags only ===")
d = make_description(ORIG, "https://www.youtube.com/watch?v=abc123", ["simpsons", "homer"])
check("no source URL in description", "youtube.com/watch" not in d and "abc123" not in d, d)
check("description mentions title", ORIG in d)
check("hashtag block at end", "#simpsons #homer" in d)

print("\n=== 5. Full metadata through uploader (dry-run, no credentials) ===")
meta = up.YouTubeUploader.generate_short_metadata(
    original_title=ORIG, original_url="https://www.youtube.com/watch?v=abc123",
    channel_name="https://www.youtube.com/@SimpsonsChannel", info={"title": ORIG},
    transcript_text="doh stupid sexy flanders", extra_hashtags="",
    title_prefix="", title_hashtags="simpsons, homer", smart_titles=False)
check("title = title + tags", meta["title"] == f"{ORIG} #simpsons #homer", meta["title"])
check("tags = user tags + clean handle, NO URL", meta["tags"] == ["simpsons", "homer", "SimpsonsChannel"], str(meta["tags"]))
check("no URL anywhere in tags", all("http" not in t and "/" not in t for t in meta["tags"]))
check("category = Entertainment (24)", meta["categoryId"] == "24")
check("desc has no URL", "youtube.com" not in meta["description"])

meta2 = up.YouTubeUploader.generate_short_metadata(
    original_title=ORIG, original_url="https://www.youtube.com/watch?v=abc123",
    channel_name="https://www.youtube.com/@SimpsonsChannel", info={"title": ORIG},
    transcript_text="", extra_hashtags="", title_prefix="", title_hashtags="", smart_titles=True)
check("no hashtags in title when field empty", "#" not in meta2["title"] and "simpsons" not in meta2["title"], meta2["title"])
check("no user tags when field empty", not any(t in meta2["tags"] for t in ["simpsons", "homer"]), str(meta2["tags"]))

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
