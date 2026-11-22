"""Synthetic fictional UTO (Utopia) TD3 passport generator.

Everything produced is fictional: invented people, the ICAO test country code UTO, illustrated
(not photographic) portraits, a visible 'DEMO - SYNTHETIC DATA' watermark, and a layout that
intentionally does not match any real passport. Not usable as a realistic forgery.
"""
from __future__ import annotations

import io
import math
import random
from dataclasses import dataclass, asdict
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from app.modules.classification import template as T
from app.modules.ocr_mrz.mrz import build_td3

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "fonts"
SCENE_W, SCENE_H = 1500, 1100
CARD_OFFSET = (128, 104)  # multiples of 8 so JPEG blocks stay aligned in 'scan' captures

SURNAMES = ["VALDRIS", "KORENTHAL", "MARQUELLE", "OSTRANDER", "BELMONTE", "TAVENSKY", "HALLORAN",
            "QUINTERO", "SOLBERG", "ARMITAGE", "DEVERAUX", "LINDQVIST", "FAIRWEATHER", "NOVAKOVIC",
            "ASHFORD", "RENWICK", "CALDERON", "WESTBROOK", "IVANOVSKI", "MORROWIND"]
GIVEN = ["ANNA MARIA", "LUCAS ELIAS", "SOFIA ISABEL", "MATEO JOSEPH", "ELENA ROSE", "NOAH ADRIAN",
         "MIRA LOUISE", "TOBIAS KAI", "ZARA NOOR", "FELIX ARTHUR", "LENA CHARLOTTE", "OMAR DANIEL",
         "IRIS JOY", "THEO MARCUS", "NINA ALEXANDRA", "RAFAEL JOHN"]
PLACES = ["NEW HARBOUR", "SILVERMERE", "NORTH ARCADIA", "LAKE VERDANT", "PORT UTOPIA", "EASTGATE"]
AUTHORITIES = ["MINISTRY OF INTERIOR", "PASSPORT OFFICE", "UTO CONSULATE"]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
TINTS = {"cream": (247, 241, 226), "sky": (232, 241, 248), "sage": (234, 243, 233), "rose": (248, 236, 236)}


def _font(kind: str, size: int):
    names = {"mono": ["DejaVuSansMono.ttf"], "bold": ["DejaVuSans-Bold.ttf"], "sans": ["DejaVuSans.ttf"],
             "monobold": ["DejaVuSansMono-Bold.ttf"]}[kind]
    for n in names:
        p = ASSETS / n
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def fmt_date(d: date) -> str:
    return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}"


@dataclass
class Person:
    person_id: str
    surname: str
    given: str
    number: str
    dob: date
    sex: str
    place: str
    issued: date
    expiry: date
    authority: str
    avatar_seed: int
    tint: str


def make_person(rng: random.Random, person_id: str, today: date | None = None, expired: bool = False) -> Person:
    today = today or date.today()
    sex = rng.choice(["M", "F"])
    dob = date(rng.randint(1958, 2004), rng.randint(1, 12), rng.randint(1, 28))
    if expired:
        issued = date(rng.randint(2010, 2015), rng.randint(1, 12), rng.randint(1, 28))
    else:
        issued = today - timedelta(days=rng.randint(200, 1800))
    expiry = date(issued.year + 10, issued.month, issued.day) - timedelta(days=1)
    return Person(
        person_id=person_id, surname=rng.choice(SURNAMES), given=rng.choice(GIVEN),
        number="UT" + "".join(str(rng.randint(0, 9)) for _ in range(7)), dob=dob, sex=sex,
        place=rng.choice(PLACES), issued=issued, expiry=expiry, authority=rng.choice(AUTHORITIES),
        avatar_seed=rng.randint(0, 10_000), tint=rng.choice(list(TINTS)),
    )


# ---------------------------------------------------------------- portrait (illustrated, not photo)
def draw_avatar(seed: int, size=(T.PHOTO_ZONE[2], T.PHOTO_ZONE[3])) -> Image.Image:
    r = random.Random(seed)
    w, h = size
    bg = tuple(r.randint(150, 215) for _ in range(3))
    img = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(img)
    for y in range(h):  # soft vertical gradient
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(c * (1 - 0.18 * t)) for c in bg))
    skin = r.choice([(240, 205, 175), (224, 172, 135), (190, 130, 95), (141, 94, 66), (105, 70, 50)])
    shirt = tuple(r.randint(30, 200) for _ in range(3))
    hair = r.choice([(30, 25, 22), (70, 45, 30), (150, 110, 60), (200, 190, 180), (20, 20, 25)])
    d.ellipse([w * 0.05, h * 0.70, w * 0.95, h * 1.35], fill=shirt)  # shoulders
    d.rectangle([w * 0.42, h * 0.58, w * 0.58, h * 0.78], fill=tuple(int(c * 0.9) for c in skin))  # neck
    hx0, hx1, hy0, hy1 = w * 0.25, w * 0.75, h * 0.17, h * 0.66
    if r.random() < 0.5:  # long hair behind
        d.ellipse([hx0 - 18, hy0 - 12, hx1 + 18, hy1 + 70], fill=hair)
    d.ellipse([hx0, hy0, hx1, hy1], fill=skin)  # head
    d.pieslice([hx0 - 6, hy0 - 14, hx1 + 6, hy0 + (hy1 - hy0) * 0.75], 180, 360, fill=hair)  # hair top
    ey = h * 0.40
    for ex in (w * 0.38, w * 0.62):
        d.ellipse([ex - 14, ey - 8, ex + 14, ey + 8], fill=(250, 250, 250))
        d.ellipse([ex - 6, ey - 6, ex + 6, ey + 6], fill=(40, 30, 25))
    d.line([(w * 0.5, h * 0.42), (w * 0.48, h * 0.50), (w * 0.52, h * 0.50)], fill=tuple(int(c * 0.75) for c in skin), width=3)
    d.arc([w * 0.4, h * 0.50, w * 0.6, h * 0.58], 15, 165, fill=(120, 50, 50), width=4)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    arr = np.asarray(img).astype(np.int16) + np.random.default_rng(seed).normal(0, 3, (h, w, 3)).astype(np.int16)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------- card rendering
def _guilloche(img: Image.Image, tint, rng: random.Random):
    d = ImageDraw.Draw(img, "RGBA")
    base = tuple(max(0, c - 28) for c in tint)
    for k in range(14):
        amp, per, ph = rng.randint(14, 40), rng.randint(120, 260), rng.random() * 6.28
        pts = [(x, 170 + k * 38 + amp * math.sin(x / per * 6.28 + ph)) for x in range(0, T.CARD_W, 8)]
        d.line(pts, fill=base + (70,), width=1)


def _stamp_layer(text_date: str, rng: random.Random) -> Image.Image:
    size = T.STAMP_ZONE[2]
    layer = Image.new("RGBA", (size + 40, size + 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = (96, 52, 150, 190)
    cx = cy = (size + 40) // 2
    d.ellipse([20, 20, 20 + size, 20 + size], outline=c, width=5)
    d.ellipse([34, 34, 6 + size, 6 + size], outline=c, width=2)
    f1, f2 = _font("bold", 14), _font("bold", 22)
    for txt, y, f in (("UTOPIA BORDER", cy - 50, f1), ("ENTRY", cy - 26, f2), (text_date, cy + 6, f1), ("DEMO", cy + 30, f1)):
        w = d.textlength(txt, font=f)
        d.text((cx - w / 2, y), txt, font=f, fill=c)
    return layer.rotate(-12, resample=Image.BICUBIC)


def draw_stamp(card: Image.Image, text_date: str, rng: random.Random):
    layer = _stamp_layer(text_date, rng)
    card.paste(layer, (T.STAMP_ZONE[0] - 20, T.STAMP_ZONE[1] - 20), layer)


def render_card(p: Person, mrz: tuple[str, str], seed: int, stamp_date: str = "14 MAR 2024") -> Image.Image:
    rng = random.Random(seed)
    tint = TINTS[p.tint]
    card = Image.new("RGB", (T.CARD_W, T.CARD_H), tint)
    _guilloche(card, tint, rng)
    d = ImageDraw.Draw(card)
    # header
    d.rectangle([0, 0, T.CARD_W, 120], fill=(20, 38, 82))
    d.text((60, 22), "REPUBLIC OF UTOPIA", font=_font("bold", 36), fill=(255, 255, 255))
    d.text((60, 72), "PASSPORT  /  PASSEPORT", font=_font("sans", 22), fill=(190, 205, 235))
    d.text((T.CARD_W - 60 - d.textlength("DEMO - SYNTHETIC DATA", font=_font("bold", 22)), 80),
           "DEMO - SYNTHETIC DATA", font=_font("bold", 22), fill=(255, 190, 80))
    d.ellipse([T.CARD_W - 150, 18, T.CARD_W - 70, 70], outline=(255, 255, 255), width=3)
    d.rectangle([0, 120, T.CARD_W, 143], fill=(255, 226, 190))
    bt = "DEMO - SYNTHETIC DATA  |  FICTIONAL PERSON  |  NOT A REAL DOCUMENT"
    d.text(((T.CARD_W - d.textlength(bt, font=_font("bold", 15))) / 2, 124), bt, font=_font("bold", 15), fill=(150, 40, 20))
    # photo
    px, py, pw, ph = T.PHOTO_ZONE
    card.paste(draw_avatar(p.avatar_seed), (px, py))
    d.rectangle([px - 3, py - 3, px + pw + 3, py + ph + 3], outline=(60, 60, 70), width=3)
    d.text((px, py + ph + 14), "ILLUSTRATED PORTRAIT", font=_font("sans", 15), fill=(120, 120, 130))
    # fields
    lab_font, val_font = _font("sans", 17), _font("bold", 33)
    values = {
        "document_type": "P", "issuer_code": "UTO", "passport_number": p.number,
        "surname": p.surname, "given_names": p.given, "nationality": "UTOPIAN",
        "date_of_birth": fmt_date(p.dob), "sex": p.sex, "place_of_birth": p.place,
        "date_of_issue": fmt_date(p.issued), "date_of_expiry": fmt_date(p.expiry), "authority": p.authority,
    }
    for name, (x, y, w, h) in T.FIELD_ZONES.items():
        d.text((x, y - 28), T.FIELD_LABELS[name], font=lab_font, fill=(95, 100, 118))
        d.text((x, y + 6), values[name], font=val_font, fill=(18, 20, 28))
    draw_stamp(card, stamp_date, rng)
    # MRZ band
    d.rectangle([20, 728, T.CARD_W - 20, 866], fill=(255, 255, 255))
    mf = _font("mono", 42)
    d.text((60, 745), mrz[0], font=mf, fill=(10, 10, 10))
    d.text((60, 803), mrz[1], font=mf, fill=(10, 10, 10))
    # watermark (low alpha so it never hides data)
    wm = Image.new("RGBA", card.size, (0, 0, 0, 0))
    wd = ImageDraw.Draw(wm)
    wf = _font("bold", 54)
    for yy in range(140, 760, 230):
        for xx in range(-200, 1250, 760):
            wd.text((xx, yy), "DEMO - SYNTHETIC DATA", font=wf, fill=(200, 40, 40, 11))
    wm = wm.rotate(12, resample=Image.BICUBIC)
    card = Image.alpha_composite(card.convert("RGBA"), wm).convert("RGB")
    return card


def values_for(p: Person) -> dict:
    return {"surname": p.surname, "given_names": p.given, "passport_number": p.number,
            "date_of_birth": fmt_date(p.dob), "date_of_expiry": fmt_date(p.expiry),
            "date_of_issue": fmt_date(p.issued), "sex": p.sex, "nationality": "UTOPIAN",
            "place_of_birth": p.place, "issuer_code": "UTO", "document_type": "P", "authority": p.authority}


def person_mrz(p: Person) -> tuple[str, str]:
    return build_td3(p.surname, p.given, p.number, "UTO", p.dob, p.sex, p.expiry)


# ---------------------------------------------------------------- tampering (applied after 1st JPEG pass)
def jpeg_roundtrip(img: Image.Image, q: int = 90) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=q, subsampling=0)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _splice_history(card: Image.Image, box, q: int = 62):
    """Simulate content pasted from a different source: the patch carries a foreign JPEG history."""
    x, y, w, h = box
    x0, y0 = (x // 8) * 8, (y // 8) * 8
    x1, y1 = min(T.CARD_W, ((x + w + 7) // 8) * 8), min(T.CARD_H, ((y + h + 7) // 8) * 8)
    patch = jpeg_roundtrip(card.crop((x0, y0, x1, y1)), q)
    card.paste(patch, (x0, y0))


def _bg_sample(card: Image.Image, box) -> tuple:
    x, y, w, h = box
    patch = np.asarray(card.crop((x - 14, y - 6, x - 2, y + h + 6)))
    return tuple(int(v) for v in np.median(patch.reshape(-1, 3), axis=0))


def tamper_text(card: Image.Image, zone: str, new_text: str):
    x, y, w, h = T.FIELD_ZONES[zone]
    d = ImageDraw.Draw(card)
    d.rectangle([x - 2, y + 2, x + w, y + h - 2], fill=_bg_sample(card, T.FIELD_ZONES[zone]))
    d.text((x, y + 6), new_text, font=_font("bold", 33), fill=(18, 20, 28))
    _splice_history(card, (x - 2, y, w + 2, h))
    return {"type": "text_edit", "zone": zone, "box": [x - 2, y, w + 2, h]}


def tamper_portrait(card: Image.Image, new_seed: int):
    px, py, pw, ph = T.PHOTO_ZONE
    card.paste(draw_avatar(new_seed), (px, py))
    _splice_history(card, (px, py, pw, ph))
    return {"type": "portrait_swap", "zone": "portrait", "box": [px, py, pw, ph]}


def tamper_stamp(card: Image.Image, new_date: str, rng: random.Random):
    x, y, w, h = T.STAMP_ZONE
    d = ImageDraw.Draw(card)
    d.rectangle([x - 22, y - 22, x + w + 22, y + h + 22], fill=_bg_sample(card, (x - 30, y, w, h)))
    draw_stamp(card, new_date, rng)
    _splice_history(card, (x - 20, y - 20, w + 40, h + 40))
    return {"type": "stamp_edit", "zone": "stamp", "box": [x - 20, y - 20, w + 40, h + 40]}


# ---------------------------------------------------------------- acquisition / degradation
def _desk(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    base = np.array([62, 55, 50], dtype=np.float32) + rng.integers(-8, 9, 3)
    yy, xx = np.mgrid[0:SCENE_H, 0:SCENE_W]
    grad = 1 + 0.10 * np.sin(xx / 210.0) + 0.06 * np.cos(yy / 160.0)
    img = base[None, None, :] * grad[..., None] + rng.normal(0, 4, (SCENE_H, SCENE_W, 1))
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def _glare(scene: Image.Image, strength: float, seed: int) -> Image.Image:
    arr = np.asarray(scene).astype(np.float32)
    yy, xx = np.mgrid[0:SCENE_H, 0:SCENE_W]
    cx, cy = CARD_OFFSET[0] + 780, CARD_OFFSET[1] + 420
    g = np.exp(-(((xx - cx) / 300.0) ** 2 + ((yy - cy) / 200.0) ** 2))
    arr += (255 * strength * g)[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def acquire(card: Image.Image, mode: str = "scan", seed: int = 0, blur: float = 0, glare: float = 0,
            crop: str | None = None, scale: float = 1.0, rotate: float = 0.0, jpeg_q: int = 90) -> Image.Image:
    """Compose the card on a desk and apply capture conditions.

    mode 'scan'  -> axis-aligned, no resampling (JPEG block grid preserved; ELA meaningful)
    mode 'photo' -> rotation + slight perspective + lighting + noise (resampled; ELA unreliable)
    """
    scene = _desk(seed)
    if mode == "photo" or rotate:
        c = card.convert("RGBA")
        c = c.rotate(rotate or random.Random(seed).uniform(-5, 5), expand=True, resample=Image.BICUBIC)
        shadow = Image.new("RGBA", c.size, (0, 0, 0, 0))
        scene.paste(Image.new("RGB", c.size, (25, 22, 20)), (CARD_OFFSET[0] + 10, CARD_OFFSET[1] + 10), c.split()[3].filter(ImageFilter.GaussianBlur(8)))
        scene.paste(c.convert("RGB"), (CARD_OFFSET[0] - (c.size[0] - T.CARD_W) // 2, CARD_OFFSET[1] - (c.size[1] - T.CARD_H) // 2), c.split()[3])
        arr = np.asarray(scene).astype(np.float32)
        yy, xx = np.mgrid[0:SCENE_H, 0:SCENE_W]
        arr *= (0.93 + 0.12 * xx / SCENE_W)[..., None]
        arr += np.random.default_rng(seed).normal(0, 3.2, arr.shape)
        scene = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    else:
        scene.paste(card, CARD_OFFSET)
    if glare:
        scene = _glare(scene, glare, seed)
    if blur:
        scene = scene.filter(ImageFilter.GaussianBlur(blur))
    if crop == "bottom":  # cuts through the MRZ
        scene = scene.crop((0, 0, SCENE_W, CARD_OFFSET[1] + 790))
    elif crop == "right":
        scene = scene.crop((0, 0, CARD_OFFSET[0] + 980, SCENE_H))
    if scale != 1.0:
        scene = scene.resize((int(scene.width * scale), int(scene.height * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    scene.save(buf, "JPEG", quality=jpeg_q, subsampling=0)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


# ---------------------------------------------------------------- sample catalogue (variants)
VARIANTS = {
    "clean": dict(title="Clean passport", expect="No issues. Everything verifies.", tamper=None),
    "bad_check_digit": dict(title="MRZ check digit error", expect="MRZ check digit FAIL (passport number digit altered).", tamper=None),
    "edited_name": dict(title="Edited surname (VIZ vs MRZ)", expect="VIZ surname differs from MRZ; ELA flags the edited region.", tamper="name"),
    "blurry": dict(title="Blurry capture", expect="Quality gate fails: recapture requested; no downstream checks.", tamper=None),
    "registry_unavailable": dict(title="Clean passport - registry outage (simulated)", expect="All checks pass; external registry UNAVAILABLE (not a fraud signal).", tamper=None),
    "edited_dob": dict(title="Edited date of birth", expect="VIZ DOB differs from MRZ; ELA flags region.", tamper="dob"),
    "portrait_swap": dict(title="Portrait swapped", expect="Portrait-region forensic anomaly (review aid); text checks pass.", tamper="portrait"),
    "stamp_edit": dict(title="Stamp date edited", expect="Stamp-region forensic anomaly (review aid).", tamper="stamp"),
    "viz_mrz_mismatch": dict(title="Passport number mismatch", expect="VIZ passport number differs from MRZ.", tamper="number"),
    "expired": dict(title="Expired passport", expect="Document-status check: EXPIRED (status, not forgery).", tamper=None),
    "glare": dict(title="Glare on document", expect="Glare detected: quality REVIEW/FAIL.", tamper=None),
    "cropped": dict(title="Cropped capture (MRZ cut off)", expect="Crop incomplete: recapture requested.", tamper=None),
    "low_res": dict(title="Low resolution", expect="Resolution too low: recapture requested.", tamper=None),
    "rotated": dict(title="Photographed at an angle", expect="Rectified automatically; ELA marked INCONCLUSIVE (resampled).", tamper=None),
}


def make_sample(variant: str, seed: int, person_id: str | None = None, session_id: str | None = None):
    """Return (jpeg_bytes, label_dict). Deterministic for (variant, seed)."""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant}")
    rng = random.Random(seed)
    p = make_person(rng, person_id or f"P{seed:05d}", expired=(variant == "expired"))
    mrz = person_mrz(p)
    truth = values_for(p)
    stamp_date = f"{rng.randint(1, 28):02d} {rng.choice(MONTHS)} {rng.randint(2022, 2025)}"
    card = render_card(p, mrz, seed, stamp_date)
    regions: list[dict] = []
    spec = VARIANTS[variant]
    cap = dict(mode="scan", seed=seed)

    if variant == "bad_check_digit":
        l2 = list(mrz[1])
        l2[9] = str((int(l2[9]) + 3) % 10)  # passport number digit altered; number itself intact
        mrz = (mrz[0], "".join(l2))
        card = render_card(p, mrz, seed, stamp_date)

    if spec["tamper"]:
        card = jpeg_roundtrip(card, 90)  # image 'history' before editing
        if spec["tamper"] == "name":
            new = rng.choice([s for s in SURNAMES if s != p.surname])
            regions.append(tamper_text(card, "surname", new))
            truth["surname_viz_edited"] = new
        elif spec["tamper"] == "dob":
            nd = date(p.dob.year + 1 if p.dob.year < 2003 else p.dob.year - 1, p.dob.month, p.dob.day)
            regions.append(tamper_text(card, "date_of_birth", fmt_date(nd)))
            truth["dob_viz_edited"] = fmt_date(nd)
        elif spec["tamper"] == "number":
            new = "UT" + "".join(str(rng.randint(0, 9)) for _ in range(7))
            regions.append(tamper_text(card, "passport_number", new))
            truth["number_viz_edited"] = new
        elif spec["tamper"] == "portrait":
            regions.append(tamper_portrait(card, p.avatar_seed + 777))
        elif spec["tamper"] == "stamp":
            regions.append(tamper_stamp(card, f"{rng.randint(1, 28):02d} {rng.choice(MONTHS)} 2026", rng))

    if variant == "blurry":
        cap.update(blur=5.5)
    elif variant == "glare":
        cap.update(glare=0.95)
    elif variant == "cropped":
        cap.update(crop="bottom")
    elif variant == "low_res":
        cap.update(scale=0.42)
    elif variant == "rotated":
        cap.update(mode="photo", rotate=-4.5)

    img = acquire(card, **cap)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    label = {
        "variant": variant, "title": spec["title"], "expected_outcome": spec["expect"], "seed": seed,
        "person_id": p.person_id, "template_id": f"{T.TEMPLATE_ID}/{p.tint}",
        "session_id": session_id or f"S{seed % 7}", "ground_truth": truth,
        "mrz": list(mrz), "tamper_regions": regions, "capture": cap,
        "synthetic": True, "watermark": "DEMO - SYNTHETIC DATA",
        "card_offset": list(CARD_OFFSET),
    }
    return buf.getvalue(), label


# Seeded demo script (PDF/brief): 5 core cases, always the same documents
DEMO_SCRIPT = [
    ("clean", 1001, {}),
    ("bad_check_digit", 1002, {}),
    ("edited_name", 1003, {}),
    ("blurry", 1004, {}),
    ("registry_unavailable", 1005, {"simulate_registry": "unavailable"}),
]
