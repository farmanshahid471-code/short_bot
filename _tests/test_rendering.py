"""
TEST 3: RENDERING - watermark position/opacity/size, aspect, fill modes,
repost copy vs render. Verified with ffprobe + PIL pixel analysis.
"""
import sys, shutil, subprocess
sys.path.insert(0, "/home/user")
from pathlib import Path
from PIL import Image

# ---------- build a deterministic test source video ----------
SRC = Path("/home/user/_tests/source_test.mp4")
EMPTY_SRT = Path("/home/user/_tests/empty.srt")
EMPTY_SRT.write_text("", encoding="utf-8")

# 1280x720 dark blue, bright vertical bar on the left edge (tests blur vs crop),
# sine audio (whisper skipped - we pass an existing empty SRT).
cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
       "-f", "lavfi", "-i", "color=c=0x141e3c:s=1280x720:d=10:r=30",
       "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
       "-filter_complex", "[0:v]drawbox=x=0:y=0:w=80:h=720:color=white@1:t=fill[v]",
       "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast",
       "-crf", "23", "-c:a", "aac", "-b:a", "128k", str(SRC)]
subprocess.run(cmd, check=True)

PASS, FAIL = [], []
def check(label, cond, extra=""):
    (PASS if cond else FAIL).append(label)
    print(("  ✅ " if cond else "  ❌ ") + label + (f"  [{extra}]" if extra and not cond else ""))

def frame(video_path, png_path, t=0.5):
    """Extract one frame of a video as a PNG for pixel analysis."""
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-ss", str(t), "-i", str(video_path), "-frames:v", "1", str(png_path)],
                   check=True)
    return Image.open(png_path)

from yt_shorts_bot.processor import VideoProcessor, BGM_ENABLED as _b
import yt_shorts_bot.processor as proc
proc.BGM_ENABLED = False          # deterministic renders (no random BGM)
from yt_shorts_bot.config import TEMP_DIR

W, H = 1080, 1440  # 3:4

def analyze_text(pil_img, y_lo, y_hi, x_lo=0.3, x_hi=0.7):
    """Find bright text pixels in a band; return (found, bbox, max_brightness)."""
    img = pil_img.convert("RGB")
    px = img.load()
    pts = []
    maxb = 0
    for y in range(y_lo, min(y_hi, img.height)):
        for x in range(int(img.width*x_lo), int(img.width*x_hi)):
            r, g, b = px[x, y]
            bri = (r+g+b)/3
            if bri > 120:
                maxb = max(maxb, bri)
                pts.append((x, y))
    if not pts:
        return False, None, 0
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    return True, (min(xs), min(ys), max(xs), max(ys)), maxb

print("\n=== A. 3:4 blur + watermarks ON (top 'SIMPSON PIMP' 50%, bottom 'LIKE & SUBSCRIBE' 100%) ===")
vp = VideoProcessor()
outA = vp.process_clip_to_short(
    SRC, output_path=TEMP_DIR/"tA.mp4", srt_path=EMPTY_SRT,
    aspect="3:4", fill="blur",
    like_subscribe=True, like_subscribe_text="LIKE & SUBSCRIBE",
    top_watermark_enabled=True, top_watermark_text="SIMPSON PIMP")
probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(outA)],
                       capture_output=True, text=True).stdout.strip()
check("3:4 output is 1080x1440", probe == "1080,1440", probe)

img = frame(outA, "_tests/fA.png")
# TOP watermark: expected y center = 12% of H = 172.8; font 56 -> span ~ y 139..207
found, box, maxb = analyze_text(img, 100, 260)
check("top watermark text present in 12% band", found, str(box))
if found:
    cx = (box[0]+box[2])/2
    cy = (box[1]+box[3])/2
    check("top watermark horizontally centered", abs(cx - W/2) < W*0.04, f"cx={cx}")
    check("top watermark at ~12% height", abs(cy - 0.12*H) < 0.04*H, f"cy={cy} vs {0.12*H}")
    check("top watermark is ~50% opacity (not full white)", 120 < maxb < 245, f"maxb={maxb}")
# BOTTOM banner: y center ~ 90% = 1296
foundB, boxB, maxbB = analyze_text(img, 1230, 1370)
check("bottom banner text present at 90% band", foundB, str(boxB))
if foundB:
    cyB = (boxB[1]+boxB[3])/2
    check("bottom banner at ~90% height", abs(cyB - 0.90*H) < 0.03*H, f"cyB={cyB}")
    check("bottom banner is 100% opacity (pure white)", maxbB > 250, f"maxbB={maxbB}")
# nothing in the middle band (no stray text)
foundM, _, _ = analyze_text(img, int(0.35*H), int(0.6*H))
check("no text in middle band (plain text, no boxes)", not foundM)

print("\n=== B. 9:16 crop + watermarks ===")
outB = vp.process_clip_to_short(
    SRC, output_path=TEMP_DIR/"tB.mp4", srt_path=EMPTY_SRT,
    aspect="9:16", fill="crop",
    like_subscribe=True, like_subscribe_text="LIKE & SUBSCRIBE",
    top_watermark_enabled=True, top_watermark_text="TOP TEST")
probeB = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(outB)],
                        capture_output=True, text=True).stdout.strip()
check("9:16 output is 1080x1920", probeB == "1080,1920", probeB)
imgB = frame(outB, "_tests/fB.png")
foundT, boxT, _ = analyze_text(imgB, int(0.12*1920-80), int(0.12*1920+120))
check("top watermark in 9:16 at ~12%", foundT, str(boxT))
# crop mode: the left-edge white bar is outside the center crop -> mostly dark frame
imgBpx = imgB.convert("RGB")
bright = sum(1 for x in range(0, 1080, 4) for y in range(0, 1920, 4)
             if (lambda p: (p[0]+p[1]+p[2])/3 > 200)(imgBpx.getpixel((x, y))))
check("crop mode: white bar cut off (frame is dark)", bright < 500, f"bright px sample={bright}")

print("\n=== C. watermarks OFF -> plain video ===")
outC = vp.process_clip_to_short(
    SRC, output_path=TEMP_DIR/"tC.mp4", srt_path=EMPTY_SRT,
    aspect="3:4", fill="blur",
    like_subscribe=False, like_subscribe_text="LIKE & SUBSCRIBE",
    top_watermark_enabled=False, top_watermark_text="")
imgC = frame(outC, "_tests/fC.png")
foundT, _, _ = analyze_text(imgC, 80, 280)
foundB, _, _ = analyze_text(imgC, 1230, 1370)
check("no top watermark when off", not foundT)
check("no bottom banner when off", not foundB)
# blur mode: white bar IS visible (foreground not cropped)
imgCpx = imgC.convert("RGB")
left_bright = sum(1 for y in range(300, 1100, 6)
                  for x in range(int(0.02*1080), int(0.2*1080), 4)
                  if (lambda p: (p[0]+p[1]+p[2])/3 > 200)(imgCpx.getpixel((x, y))))
check("blur mode: white bar still visible (nothing cut)", left_bright > 50, f"bright={left_bright}")

print("\n=== D. REPOST bot: copy mode keeps original (NO watermark) ===")
from yt_shorts_repost_bot.reprocessor import ShortReprocessor
rp = ShortReprocessor()
outD = rp.process_short(SRC, output_path=TEMP_DIR/"tD.mp4", mode="copy")
probeD = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(outD)],
                        capture_output=True, text=True).stdout.strip()
check("copy mode keeps original 1280x720", probeD == "1280,720", probeD)
imgD = frame(outD, "_tests/fD.png").convert("RGB")
imgS = frame(SRC, "_tests/fS.png").convert("RGB")
import random
random.seed(1)
diff = sum(abs(imgD.getpixel((x, y))[0] - imgS.getpixel((x, y))[0])
           for x, y in [(random.randrange(0, 1280), random.randrange(0, 720)) for _ in range(200)])
check("copy mode pixel-identical (re-encode only)", diff == 0, f"diff={diff}")

print("\n=== E. REPOST bot: render mode burns watermarks ===")
import yt_shorts_repost_bot.processor as rproc
rproc.BGM_ENABLED = False
# avoid whisper: monkeypatch transcription to write an empty SRT
orig_transcribe = rproc.VideoProcessor.transcribe_and_generate_srt
def fake_transcribe(self, video_path, srt_path=None, mode="viral"):
    p = Path(srt_path) if srt_path else video_path.with_suffix(".srt")
    p.write_text("", encoding="utf-8")
    return p
rproc.VideoProcessor.transcribe_and_generate_srt = fake_transcribe
outE = rp.process_short(SRC, output_path=TEMP_DIR/"tE.mp4", mode="render",
                        like_subscribe=True, like_subscribe_text="SUBSCRIBE",
                        top_watermark_enabled=True, top_watermark_text="MY CHANNEL")
probeE = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(outE)],
                        capture_output=True, text=True).stdout.strip()
imgE = frame(outE, "_tests/fE.png")
check("render mode -> 1080x1920 (repost default 9:16)", probeE == "1080,1920", probeE)
foundT, _, _ = analyze_text(imgE, 80, 300)
foundB, _, _ = analyze_text(imgE, int(0.90*imgE.height-90), int(0.90*imgE.height+90))
check("render mode has top watermark", foundT)
check("render mode has bottom banner", foundB)
rproc.VideoProcessor.transcribe_and_generate_srt = orig_transcribe

print("\n=== F. metadata sidecar (.txt next to finished Short) ===")
from yt_shorts_bot.hashtags import save_metadata_sidecar
side = save_metadata_sidecar(outA, {"title": "TEST TITLE", "description": "TEST DESC", "tags": ["simpsons"]},
                             source_url="https://youtu.be/abc", short_id="mock_1", account="Gaming")
check("sidecar .txt written", side is not None and side.exists())
if side:
    txt = side.read_text(encoding="utf-8")
    check("sidecar contains title", "TITLE         : TEST TITLE" in txt)
    check("sidecar contains source url", "Source URL    : https://youtu.be/abc" in txt)
    check("sidecar marks dry run vs uploaded", "mock_1" in txt)

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("FAILED:", *FAIL, sep="\n  - ")
    sys.exit(1)
print("ALL TESTS PASSED ✅")
