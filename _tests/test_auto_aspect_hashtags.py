"""
TEST 11: Auto aspect (like the original - no blur bars) + hashtag guarantees.
Proof of no bars: when the output aspect EXACTLY equals the source aspect, the
frame fills the canvas 100% - blur bars/pillarbox are mathematically impossible.
"""
import sys, subprocess
sys.path.insert(0, "/home/user")
from pathlib import Path

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

def make_src(path, w, h):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:d=3:r=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-c:a", "aac", "-shortest", str(path)], check=True)

def probe_size(path):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                          capture_output=True, text=True).stdout.strip()

def aspect(s):
    w, h = s.split(",")
    return int(w) / int(h)

import yt_shorts_bot.processor as proc
proc.BGM_ENABLED = False
from yt_shorts_bot.processor import VideoProcessor
vp = VideoProcessor()

print("\n=== 1. aspect=auto: output aspect == source aspect (NO bars possible) ===")
for label, (sw, sh) in {"9:16": (720, 1280), "3:4": (720, 960), "4:5": (800, 1000),
                        "1:1": (720, 720), "16:9": (1280, 720)}.items():
    src = Path(f"/tmp/t_src_{label.replace(':','_')}.mp4")
    make_src(src, sw, sh)
    out = vp.process_clip_to_short(src, output_path=Path(f"/tmp/t_auto_{label.replace(':','_')}.mp4"),
                                   srt_path=Path("/tmp/t_empty.srt").write_text("") or Path("/tmp/t_empty.srt"),
                                   aspect="auto", like_subscribe=False, top_watermark_enabled=False, subtitles=False)
    ps = probe_size(out)
    check(f"{label} source -> output {ps} (same aspect)",
          abs(aspect(ps) - sw / sh) < 0.01, ps)

print("\n=== 2. control: old 3:4+blur on 9:16 -> DIFFERENT aspect (bars exist) ===")
src9 = Path("/tmp/t_src_9_16.mp4")
out_old = vp.process_clip_to_short(src9, output_path=Path("/tmp/t_old.mp4"),
                                   srt_path=Path("/tmp/t_empty.srt"), aspect="3:4", fill="blur",
                                   like_subscribe=False, top_watermark_enabled=False, subtitles=False)
ps_old = probe_size(out_old)
check("old config output is 1080x1440 (3:4) - bars possible", ps_old == "1080,1440", ps_old)
check("old config aspect != source aspect => bars exist", abs(aspect(ps_old) - 720 / 1280) > 0.05)

print("\n=== 3. auto mode still burns watermarks ===")
out_wm = vp.process_clip_to_short(src9, output_path=Path("/tmp/t_wm.mp4"),
                                  srt_path=Path("/tmp/t_empty.srt"), aspect="auto",
                                  like_subscribe=True, like_subscribe_text="SUBSCRIBE",
                                  top_watermark_enabled=True, top_watermark_text="TOP", subtitles=False)
subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", "0.8", "-i", str(out_wm), "-frames:v", "1", "/tmp/t_wm.png"], check=True)
from PIL import Image
img = Image.open("/tmp/t_wm.png").convert("RGB")
px = img.load(); w, h = img.size
bright_bottom = sum(1 for x in range(w//3, 2*w//3, 4) for y in range(int(h*0.87), int(h*0.97), 4)
                    if (px[x, y][0] + px[x, y][1] + px[x, y][2]) / 3 > 150)
bright_top = sum(1 for x in range(w//3, 2*w//3, 4) for y in range(int(h*0.05), int(h*0.2), 4)
                 if (px[x, y][0] + px[x, y][1] + px[x, y][2]) / 3 > 150)
check("bottom watermark burned in auto mode", bright_bottom > 20, str(bright_bottom))
check("top watermark burned in auto mode", bright_top > 20, str(bright_top))

print("\n=== 4. Repost defaults: no aspect set -> auto ===")
import yt_shorts_repost_bot.scheduler as sched_mod
import yt_shorts_repost_bot.main as main_mod
s_src = open(sched_mod.__file__).read(); m_src = open(main_mod.__file__).read()
check("repost scheduler defaults aspect to 'auto'", "or \"auto\"" in s_src or "or 'auto'" in s_src)
check("repost main defaults aspect to 'auto'", "or \"auto\"" in m_src or "or 'auto'" in m_src)

print("\n=== 5. Hashtags: user-only, always preserved ===")
from yt_shorts_bot.hashtags import build_hashtags, make_catchy_title, make_description
info = {"title": "Peter's fancy puking hat 🎩 #familyguy #funny"}
tags = build_hashtags(info=info, title_hashtags="familyguy,peter,brian,stewie")
check("user tags exactly", tags == ["familyguy", "peter", "brian", "stewie"], str(tags))
t = make_catchy_title(info=info, title_prefix="", title_hashtags="familyguy,peter,brian,stewie", smart_titles=True)
check("title has ONLY user's 4 tags", t.count("#") == 4 and "#familyguy #funny" not in t, t)
d = make_description(info["title"], "", tags)
check("description has no source hashtags", "#familyguy #funny" not in d and "#familyguy #peter #brian #stewie" in d)
t_long = make_catchy_title(info={"title": "A" * 90}, title_prefix="", title_hashtags="familyguy,peter,brian,stewie")
check("long title: <=100 chars AND hashtags kept", len(t_long) <= 100 and "#familyguy #peter #brian #stewie" in t_long, t_long)

print("\n=== 6. Repost webui: auto option present + default ===")
from yt_shorts_repost_bot import webui as rweb
h = rweb._render_page(loaded_account="x")
check("dropdown offers 'auto (like the original'", "auto (like the original" in h)
check("auto is the pre-selected default", 'value="auto" selected' in h)

for p in Path("/tmp").glob("t_*"): 
    try: p.unlink()
    except Exception: pass

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
