"""Build the SYNTHETIC DEMO FIXTURE video + matching caption file used to test real frame capture.

Why: YouTube video streams can't be downloaded under YouTube's terms, so testing the frame pipeline
needs a video file we are allowed to use. This script renders simple lecture slides (Pillow), narrates
them with macOS `say`, and muxes them with ffmpeg. The output is clearly labeled as synthetic on every
slide. It is a test fixture, not health guidance.

Usage (macOS, needs ffmpeg):  backend/.venv/bin/python scripts/make_demo_video.py
Outputs: backend/data/fixtures/demo_fatigue_lecture.mp4 and .vtt
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "backend" / "data" / "fixtures"
W, H = 1280, 720
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
INK, GREEN, PAPER, CLAY = (40, 40, 36), (79, 111, 82), (251, 247, 239), (154, 74, 42)

SLIDES = [
    {"title": "Understanding Fatigue", "kind": "title",
     "say": ["Welcome. Today we talk about fatigue, one of the most common complaints in Hashimoto's disease and Sjögren's disease.",
             "This is a short demonstration lecture."]},
    {"title": "How thyroid hormone affects energy", "kind": "pathway",
     "say": ["Thyroid hormones control how your body uses energy.",
             "The brain sends T S H, thyroid stimulating hormone, to the thyroid, which makes T4 and T3.",
             "In Hashimoto's, the immune system damages the thyroid, so it may not make enough hormone. That is hypothyroidism, and fatigue is a common symptom."]},
    {"title": "Why tiredness can continue", "kind": "bullets",
     "bullets": ["Thyroid hormone level", "Sleep problems", "Sjögren's disease itself", "Low iron or anemia", "Mood and stress"],
     "say": ["Fatigue can have many causes.",
             "Even when thyroid levels are treated, tiredness may continue, because sleep problems, Sjögren's disease, low iron, or mood can all play a part.",
             "Ask your doctor which tests make sense for you."]},
    {"title": "Taking levothyroxine", "kind": "timeline",
     "say": ["Many doctors advise taking levothyroxine on an empty stomach in the morning.",
             "Then wait thirty to sixty minutes before breakfast or coffee, because some foods and drinks can reduce how well it is absorbed."]},
    {"title": "A claim to check: gluten", "kind": "claim",
     "say": ["Now my own opinion.",
             "Many of my patients say they feel more energetic after cutting out gluten.",
             "I believe a gluten-free diet can reverse Hashimoto's for many people."]},
    {"title": "Questions for your doctor", "kind": "bullets",
     "bullets": ["Is my thyroid level in range?", "Could something else explain my tiredness?", "Should my diet change?"],
     "say": ["Bring your questions to your next appointment.", "Thank you for watching."]},
]


def font(size: int, bold: bool = False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


def render(slide: dict, path: Path) -> None:
    im = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 14], fill=GREEN)
    d.text((60, 50), slide["title"], font=font(54, True), fill=INK)
    k = slide["kind"]
    if k == "title":
        d.text((60, 160), "Hashimoto's  &  Sjögren's", font=font(40), fill=GREEN)
        for i, r in enumerate((110, 80, 50)):
            d.ellipse([900 - r, 420 - r, 900 + r, 420 + r], outline=GREEN, width=8 - i * 2)
    elif k == "pathway":
        boxes = [("Brain", "sends TSH"), ("Thyroid", "makes T4, T3"), ("Body", "uses energy")]
        for i, (a, b) in enumerate(boxes):
            x = 70 + i * 410
            d.rounded_rectangle([x, 230, x + 320, 430], radius=24, fill=(232, 239, 228), outline=GREEN, width=5)
            d.text((x + 30, 265), a, font=font(48, True), fill=INK)
            d.text((x + 30, 345), b, font=font(34), fill=INK)
            if i < 2:
                d.line([x + 330, 330, x + 400, 330], fill=INK, width=8)
                d.polygon([(x + 400, 312), (x + 400, 348), (x + 405 + 0, 330)], fill=INK)
                d.polygon([(x + 392, 310), (x + 392, 350), (x + 410, 330)], fill=INK)
        d.text((70, 500), "Hashimoto's: immune system damages the thyroid", font=font(36), fill=CLAY)
        d.text((70, 550), "-> less hormone (hypothyroidism) -> fatigue is common", font=font(36), fill=CLAY)
    elif k == "bullets":
        for i, b in enumerate(slide["bullets"]):
            y = 180 + i * 85
            d.ellipse([70, y + 12, 96, y + 38], fill=GREEN)
            d.text((120, y), b, font=font(44), fill=INK)
    elif k == "timeline":
        d.line([120, 380, 1160, 380], fill=INK, width=6)
        for x, top, bot in ((160, "7:00 am", "Pill, water only"), (620, "+30-60 min", "Wait"), (1080, "Then", "Breakfast / coffee")):
            d.ellipse([x - 22, 358, x + 22, 402], fill=GREEN)
            d.text((x - 90, 270), top, font=font(40, True), fill=INK)
            d.text((x - 120, 430), bot, font=font(36), fill=INK)
    elif k == "claim":
        d.rounded_rectangle([70, 190, W - 70, 470], radius=20, fill=(246, 230, 220), outline=CLAY, width=5)
        d.text((110, 220), "Speaker's opinion:", font=font(38, True), fill=CLAY)
        d.text((110, 290), '"A gluten-free diet can reverse', font=font(46), fill=INK)
        d.text((110, 350), "Hashimoto's for many people.\"", font=font(46), fill=INK)
        d.text((110, 520), "(Personal experience, not a study)", font=font(34), fill=INK)
    d.rectangle([0, H - 54, W, H], fill=(60, 60, 54))
    d.text((24, H - 44), "SYNTHETIC DEMO FIXTURE - made for testing UmmaCare - not medical advice", font=font(26), fill=(255, 255, 255))
    im.save(path)


def dur(p: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def ts(t: float) -> str:
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    cues, concat_v, concat_a, t = [], [], [], 0.0
    gap = 0.4
    for i, s in enumerate(SLIDES):
        img = tmp / f"s{i}.png"
        render(s, img)
        slide_len = 0.0
        for j, sentence in enumerate(s["say"]):
            a = tmp / f"a{i}_{j}.aiff"
            subprocess.run(["say", "-v", "Samantha", "-r", "165", "-o", str(a), sentence], check=True)
            wav = tmp / f"a{i}_{j}.wav"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(a), "-af", f"apad=pad_dur={gap}", "-ar", "44100", "-ac", "1", str(wav)], check=True)
            d = dur(wav)
            cues.append((t + slide_len, t + slide_len + d - gap, sentence))
            concat_a.append(wav)
            slide_len += d
        concat_v.append((img, slide_len))
        t += slide_len
    (tmp / "v.txt").write_text("".join(f"file '{p}'\nduration {d:.3f}\n" for p, d in concat_v) + f"file '{concat_v[-1][0]}'\n")
    (tmp / "a.txt").write_text("".join(f"file '{p}'\n" for p in concat_a))
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "a.txt"), str(tmp / "audio.m4a")], check=True)
    mp4 = OUT / "demo_fatigue_lecture.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(tmp / "v.txt"), "-i", str(tmp / "audio.m4a"),
                    "-vf", "fps=10,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30", "-c:a", "aac", "-b:a", "64k",
                    "-shortest", str(mp4)], check=True)
    vtt = ["WEBVTT", "NOTE SYNTHETIC DEMO FIXTURE generated by scripts/make_demo_video.py", ""]
    for a, b, text in cues:
        vtt += [f"{ts(a)} --> {ts(b)}", text, ""]
    (OUT / "demo_fatigue_lecture.vtt").write_text("\n".join(vtt))
    print(f"wrote {mp4} ({mp4.stat().st_size // 1024} KB, {t:.1f}s) and {len(cues)} caption cues")


if __name__ == "__main__":
    main()
