"""Render the SYNTHETIC DEMO FIXTURE 'magazine clipping' photo used to test photo/cutout discovery."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent.parent / "backend" / "data" / "fixtures" / "magazine_clipping.jpg"
im = Image.new("RGB", (1000, 1250), (236, 230, 214))
d = ImageDraw.Draw(im)
paper = [(60, 50), (950, 70), (930, 1200), (40, 1180)]
d.polygon(paper, fill=(252, 249, 240))
H = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia Bold.ttf", 44)
B = ImageFont.truetype("/System/Library/Fonts/Supplemental/Georgia.ttf", 27)
S = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 20)
d.text((100, 110), "Dry Eyes After 50?", font=H, fill=(30, 30, 30))
d.text((100, 175), "Five habits that may help", font=B, fill=(90, 90, 90))
body = ["Dry, gritty eyes are common with age and with",
        "conditions such as Sjogren's. Our experts suggest:",
        "",
        "1. Use a humidifier where you sleep.",
        "2. Follow the 20-20-20 rule at screens: every",
        "   20 minutes, look 20 feet away for 20 seconds.",
        "3. Choose preservative-free drops if you use them",
        "   more than four times a day.",
        "4. Omega-3 fish oil supplements cure dry eye in",
        "   most people within a month.",
        "5. Ask your eye doctor about tear-duct plugs.",
        "",
        "Talk to your doctor before starting supplements."]
for i, t in enumerate(body):
    d.text((100, 250 + i * 46), t, font=B, fill=(40, 40, 40))
d.text((100, 1120), "SYNTHETIC DEMO FIXTURE - invented clipping for testing UmmaCare", font=S, fill=(130, 130, 130))
im = im.rotate(2, fillcolor=(236, 230, 214)).filter(ImageFilter.GaussianBlur(0.5))
im.save(OUT, quality=88)
print("wrote", OUT)
