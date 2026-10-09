#!/usr/bin/env python3
"""Génère toutes les icônes de Tratra depuis le logo officiel : frontend/public/tratra_logo.webp.

Usage : python3 design-system/build-icons.py      (Pillow requis : pip install pillow)
Sorties :
  - web  : src/app/icon.png (favicon), src/app/apple-icon.png, public/icons/*
  - Flutter (TRATRA_FLUTTER_DIR, défaut ../handy_tratra/flutter_tratra) : assets/images/tratra_logo.webp,
    mipmaps Android, AppIcon iOS, favicon + icônes Flutter Web
  - backend : static/img/tratra_logo.webp et favicon.png
Le logo officiel est la SEULE source : ne jamais retoucher les icônes à la main.
"""
import json, os, shutil, sys
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
FE = HERE.parent
REPO = FE.parent
FL = Path(os.environ.get("TRATRA_FLUTTER_DIR", REPO.parent / "handy_tratra" / "flutter_tratra"))
SRC = FE / "public" / "tratra_logo.webp"
WHITE = (255, 255, 255, 255)

logo = Image.open(SRC).convert("RGBA")
crop = logo.crop(logo.getchannel("A").getbbox())  # contenu utile, sans marge
side = max(crop.size)
square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
square.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))


def make(size, bg=None, scale=0.78):
    canvas = Image.new("RGBA", (size, size), bg or (0, 0, 0, 0))
    n = max(1, round(size * scale))
    canvas.alpha_composite(square.resize((n, n), Image.LANCZOS), ((size - n) // 2, (size - n) // 2))
    return canvas


def save(path, img, opaque=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    (img.convert("RGB") if opaque else img).save(path, optimize=True)


# ---- Web ----
save(FE / "src/app/icon.png", make(64, None, 0.96))
save(FE / "src/app/apple-icon.png", make(180, WHITE, 0.74), True)
save(FE / "public/icons/icon-192.png", make(192, WHITE, 0.76), True)
save(FE / "public/icons/icon-512.png", make(512, WHITE, 0.76), True)
save(FE / "public/icons/maskable-512.png", make(512, WHITE, 0.56), True)  # zone de sécurité 80 %

# ---- Backend (admin, e-mails) ----
static = REPO / "static" / "img"
if static.exists():
    shutil.copyfile(SRC, static / "tratra_logo.webp")
    save(static / "favicon.png", make(32, None, 0.96))

# ---- Flutter ----
if FL.exists():
    (FL / "assets/images").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SRC, FL / "assets/images/tratra_logo.webp")
    for density, px in {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}.items():
        save(FL / f"android/app/src/main/res/mipmap-{density}/ic_launcher.png", make(px, WHITE, 0.80), True)
    base = FL / "ios/Runner/Assets.xcassets/AppIcon.appiconset"
    for im in json.loads((base / "Contents.json").read_text())["images"]:
        px = round(float(im["size"].split("x")[0]) * int(im["scale"].rstrip("x")))
        save(base / im["filename"], make(px, WHITE, 0.78), True)
    for f in (FL / "web/icons").glob("*.png"):
        save(f, make(Image.open(f).size[0], WHITE, 0.56 if "maskable" in f.name else 0.76), True)
    fav = FL / "web/favicon.png"
    if fav.exists():
        save(fav, make(Image.open(fav).size[0], None, 0.96))
else:
    print(f"[icons] Dossier Flutter introuvable ({FL}) — sorties Flutter ignorées.", file=sys.stderr)
print("[icons] icônes régénérées depuis", SRC)
