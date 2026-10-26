"""Render the SYNTHETIC DEMO FIXTURE 'photo of a handwritten note' used to test image-note reading.
One word is deliberately scribbled over so the reader must mark it [illegible] instead of guessing."""
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent / "backend" / "data" / "fixtures" / "handwritten_note.jpg"
random.seed(7)
im = Image.new("RGB", (1100, 820), (250, 246, 228))
d = ImageDraw.Draw(im)
for y in range(120, 800, 52):
    d.line([40, y, 1060, y], fill=(170, 195, 220), width=2)
d.line([110, 0, 110, 820], fill=(225, 150, 150), width=2)
f = ImageFont.truetype("/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf", 38)
lines = ["Oct 19 - eye doctor visit", "Dr. Lee says use the preservative-free", "drops 4 times a day. Maybe plugs later.",
         "Eyes worse when reading on the tablet.", "Ask Dr. Kim: is the selenium making me", "tired? Bring list of all my pills."]
for i, t in enumerate(lines):
    d.text((130 + random.randint(-4, 4), 78 + i * 104), t, font=f, fill=(30, 40, 90))
# scribble over the word "selenium"
y0 = 78 + 4 * 104
x0 = 128 + d.textlength("Ask Dr. Kim: is the ", font=f)
x1 = 128 + d.textlength("Ask Dr. Kim: is the selenium", font=f) + 6
for _ in range(110):
    d.line([random.uniform(x0, x1), y0 + random.randint(2, 48), random.uniform(x0, x1), y0 + random.randint(2, 48)], fill=(30, 40, 90), width=5)
d.text((700, 760), "SYNTHETIC DEMO FIXTURE", font=ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22), fill=(120, 120, 120))
im = im.rotate(-1.5, expand=False, fillcolor=(235, 230, 215)).filter(ImageFilter.GaussianBlur(0.6))
im.save(OUT, quality=88)
print("wrote", OUT)
