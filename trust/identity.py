"""Tratra ID : identifiant professionnel, QR permanent, QR de mission temporaire, badge imprimable.

Principes de sécurité
- Le QR permanent n'encode que l'URL de vérification (`<PUBLIC_WEB_URL>/verify/<code>`) : jamais de document,
  de numéro d'identité, de téléphone ni d'e-mail.
- La validité est RECALCULÉE à chaque vérification (règle d'éligibilité : KYC approuvé, compte actif, profil
  validé) : suspension ou KYC invalide = badge révoqué immédiatement, sans cache.
- Le QR de mission est court (15 min), à usage unique, lié à une réservation, réservé à son client et révoqué par
  le suivant ; seule l'empreinte SHA-256 du jeton est stockée.
"""
import base64
import hashlib
import io
import re
import secrets
from datetime import timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple

import qrcode
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from handy.api.serializers import absolute_media_url, public_display_name
from handy.eligibility import is_publishable
from handy.models import Booking, HandymanProfile
from trust import passport
from trust.models import BadgeAward, BookingPass, IdentityCheck, ProfessionalId, audit

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sans 0/O/1/I/L : lisible à voix haute
CODE_RE = re.compile(r"^TR-[A-HJKMNP-Z2-9]{4}-[A-HJKMNP-Z2-9]{4}$")

PASS_TTL = timedelta(minutes=15)
PASS_OPENS_BEFORE = timedelta(hours=3)    # le QR de mission n'est délivré que peu avant l'intervention…
PASS_CLOSES_AFTER = timedelta(hours=12)   # …et jusqu'à quelques heures après l'heure prévue
PASS_BOOKING_STATUSES = ("confirmed", "in_progress")

ASSETS = Path(__file__).resolve().parent / "assets"


class IdentityError(Exception):
    """Erreur métier de vérification : `code` stable (lisible par les clients), `detail` affichable, `status` HTTP."""

    def __init__(self, code: str, detail: str, status: int = 400, **extra):
        super().__init__(detail)
        self.code, self.detail, self.status, self.extra = code, detail, status, extra

    def payload(self) -> Dict:
        return {"valid": False, "code": self.code, "detail": self.detail, **self.extra}


# ---- Identifiant ---------------------------------------------------------------------------------

def new_code() -> str:
    pick = lambda: "".join(secrets.choice(ALPHABET) for _ in range(4))  # noqa: E731
    return f"TR-{pick()}-{pick()}"


def normalize_code(raw: str) -> Optional[str]:
    """Accepte un code nu (« tr-abcd-efgh ») ou l'URL complète du QR ; renvoie le code canonique ou None."""
    value = (raw or "").strip()
    if "/" in value:
        value = value.rstrip("/").rsplit("/", 1)[-1]
    value = value.upper()
    return value if CODE_RE.match(value) else None


def ensure_id(profile: HandymanProfile) -> ProfessionalId:
    existing = ProfessionalId.objects.filter(profile=profile).first()
    if existing:
        return existing
    for _ in range(8):
        try:
            with transaction.atomic():
                created = ProfessionalId.objects.create(profile=profile, code=new_code())
            audit("tratra_id.issued", target=profile, code=created.code)
            return created
        except IntegrityError:
            existing = ProfessionalId.objects.filter(profile=profile).first()  # course : créé entre-temps
            if existing:
                return existing
    raise RuntimeError("Impossible de générer un identifiant Tratra ID unique.")


def verify_url(code: str) -> str:
    return f"{settings.PUBLIC_WEB_URL}/verify/{code}"


def pass_url(token: str) -> str:
    return f"{settings.PUBLIC_WEB_URL}/verify/pass/{token}"


def is_valid(profile: HandymanProfile) -> bool:
    """Le badge est valide si et seulement si l'artisan est aujourd'hui éligible (KYC approuvé, compte actif…)."""
    return is_publishable(profile)


# ---- QR ---------------------------------------------------------------------------------------------

def qr_image(data: str, *, box_size: int = 10) -> Image.Image:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="#0B1210", back_color="white").convert("RGB")


def qr_png(data: str) -> bytes:
    buf = io.BytesIO()
    qr_image(data).save(buf, "PNG")
    return buf.getvalue()


def qr_data_url(data: str) -> str:
    return "data:image/png;base64," + base64.b64encode(qr_png(data)).decode()


# ---- Payloads -----------------------------------------------------------------------------------------

def holder(profile: HandymanProfile, request=None, *, full_name: bool = False) -> Dict:
    """Ce que voit celui qui vérifie : jamais de document, de numéro, de téléphone ni d'e-mail."""
    user = profile.user
    name = (user.get_full_name() or "").strip() if full_name else ""
    return {
        "display_name": name or public_display_name(user),
        "photo": absolute_media_url(request, profile.photo),
        "trades": [c.name for c in profile.skills.all()],
        "commune": profile.commune or "",
        "badges": passport.badges_of(profile),
        "kyc_verified_on": passport._kyc_verified_on(profile),
    }


def public_verification(raw_code: str, request=None) -> Tuple[int, Dict]:
    """Vérification publique d'un QR permanent. (statut HTTP, charge utile) — forme uniforme pour tout code."""
    code = normalize_code(raw_code)
    pro = (ProfessionalId.objects.select_related("profile", "profile__user").filter(code=code).first()
           if code else None)
    if pro is None:
        return 404, {"valid": False, "status": "unknown", "tratra_id": code or "",
                     "message": "Ce code Tratra ID n'existe pas. Ne faites pas confiance à ce badge."}
    profile = pro.profile
    if not is_valid(profile):
        # Révocation immédiate : plus aucun détail personnel n'est divulgué.
        return 200, {"valid": False, "status": "revoked", "tratra_id": pro.code,
                     "message": "Ce professionnel n'est plus vérifié par Tratra. Ne le laissez pas intervenir "
                                "en son nom et contactez le support."}
    return 200, {"valid": True, "status": "active", "tratra_id": pro.code,
                 "message": "Professionnel vérifié par Tratra.", "holder": holder(profile, request),
                 "checked_at": timezone.now()}


def my_id(profile: HandymanProfile, request=None) -> Dict:
    """Tratra ID du propriétaire (badge numérique + QR permanent). Créé à la première demande."""
    pro = ensure_id(profile)
    valid = is_valid(profile)
    url = verify_url(pro.code)
    return {
        "tratra_id": pro.code,
        "issued_at": pro.created_at,
        "status": "active" if valid else "suspended",
        "valid": valid,
        "message": ("Badge actif : les clients peuvent vérifier votre identité professionnelle."
                    if valid else
                    "Badge suspendu : il redevient actif dès que votre identité est vérifiée par l'équipe Tratra."),
        "verify_url": url,
        "qr": qr_data_url(url),
        "holder": holder(profile, request, full_name=True),
        "pdf_available": valid,
    }


# ---- QR de mission --------------------------------------------------------------------------------------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_pass(booking: Booking, user) -> Dict:
    """L'artisan de la réservation obtient un QR de mission (15 min, usage unique). Le précédent est révoqué."""
    if booking.handyman_id != user.id:
        raise IdentityError("forbidden", "Seul l'artisan de cette réservation peut afficher son QR de mission.", 403)
    if booking.status not in PASS_BOOKING_STATUSES:
        raise IdentityError("booking_not_active", "Le QR de mission n'est disponible que pour une mission confirmée "
                                                  "ou en cours.")
    now = timezone.now()
    if not (booking.booking_date - PASS_OPENS_BEFORE <= now <= booking.booking_date + PASS_CLOSES_AFTER):
        raise IdentityError("outside_window", "Le QR de mission est disponible quelques heures avant l'heure prévue "
                                              "de l'intervention.")
    profile = HandymanProfile.objects.select_related("user").get(user_id=user.id)
    if not is_valid(profile):
        raise IdentityError("not_verified", "Votre identité n'est pas (ou plus) vérifiée : le QR de mission est "
                                            "indisponible.", 409)
    token = secrets.token_urlsafe(24)
    with transaction.atomic():
        BookingPass.objects.filter(booking=booking, used_at__isnull=True, revoked_at__isnull=True).update(revoked_at=now)
        created = BookingPass.objects.create(booking=booking, token_hash=_hash(token), created_by=user,
                                             expires_at=now + PASS_TTL)
    url = pass_url(token)
    return {"token": token, "url": url, "qr": qr_data_url(url), "expires_at": created.expires_at,
            "ttl_seconds": int(PASS_TTL.total_seconds()), "booking_id": booking.id}


def consume_pass(token: str, user, request=None) -> Dict:
    """Le CLIENT de la réservation scanne le QR de mission : l'identité de l'artisan est confirmée et le QR
    consommé. Toute autre personne reçoit la même réponse qu'un QR inconnu (aucune fuite)."""
    unknown = IdentityError("unknown", "Ce QR ne correspond à aucune de vos réservations.", 404)
    token = (token or "").strip().rsplit("/", 1)[-1]
    if not token or len(token) > 128:
        raise unknown
    now = timezone.now()
    with transaction.atomic():
        row = (BookingPass.objects.select_for_update(of=("self",))
               .select_related("booking", "booking__service", "booking__handyman")
               .filter(token_hash=_hash(token)).first())
        if row is None or row.booking.client_id != user.id:
            raise unknown
        booking = row.booking
        if row.used_at is not None:
            raise IdentityError("used", "Ce QR a déjà été utilisé : l'identité de l'artisan a déjà été vérifiée.", 409,
                                verified_at=row.used_at)
        if row.revoked_at is not None:
            raise IdentityError("replaced", "Ce QR a été remplacé par un plus récent. Demandez à l'artisan de "
                                            "l'afficher à nouveau.", 410)
        if row.expires_at <= now:
            raise IdentityError("expired", "Ce QR a expiré. Demandez à l'artisan d'en afficher un nouveau.", 410)
        if booking.status not in PASS_BOOKING_STATUSES:
            raise IdentityError("booking_not_active", "Cette réservation n'est plus en cours.", 400)
        profile = (HandymanProfile.objects.select_related("user").prefetch_related("skills")
                   .filter(user_id=booking.handyman_id).first())
        if profile is None or not is_valid(profile):
            raise IdentityError("revoked", "Cet artisan n'est plus vérifié par Tratra. Ne le laissez pas intervenir "
                                           "et contactez le support.", 409)
        row.used_at, row.used_by = now, user
        row.save(update_fields=["used_at", "used_by"])
        check = IdentityCheck.objects.create(booking=booking, professional=ensure_id(profile), checked_by=user)
        audit("identity.verified", actor=user, target=booking, target_type="booking", professional=check.professional.code)
    return {"valid": True, "matches_booking": True, "booking_id": booking.id,
            "service": booking.service.title if booking.service_id else "",
            "booking_date": booking.booking_date, "verified_at": check.verified_at,
            "tratra_id": check.professional.code, "holder": holder(profile, request),
            "message": "Identité confirmée : c'est bien l'artisan attendu pour cette réservation."}


def booking_identity(booking: Booking) -> Dict:
    """État de la vérification d'identité d'une réservation (visible par ses deux participants)."""
    last = booking.identity_checks.select_related("professional").first()
    return {"booking_id": booking.id, "verified": last is not None,
            "verified_at": last.verified_at if last else None,
            "tratra_id": last.professional.code if last else None}


# ---- Badge imprimable (PDF) ----------------------------------------------------------------------------------

GREEN, GREEN_DARK, YELLOW = (46, 139, 87), (31, 106, 65), (246, 201, 14)
INK, ASH, SOFT, WHITE = (15, 23, 42), (107, 114, 128), (232, 246, 238), (255, 255, 255)


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / "fonts" / f"Poppins-{weight}.ttf"), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    while text and draw.textlength(text, font=font) > max_width:
        text = text[:-2].rstrip() + "…" if len(text) > 2 else ""
    return text


def _portrait(profile: HandymanProfile, name: str, size: int) -> Image.Image:
    """Photo réelle recadrée en disque ; sinon initiales sur fond de marque (jamais de photo de stock)."""
    img = None
    if profile.photo:
        try:
            with profile.photo.open("rb") as fh:
                img = Image.open(fh).convert("RGB")
                img.load()
        except Exception:  # fichier absent/illisible : repli sur les initiales
            img = None
    if img is not None:
        side = min(img.size)
        left, top = (img.width - side) // 2, (img.height - side) // 2
        img = img.crop((left, top, left + side, top + side)).resize((size, size), Image.LANCZOS)
    else:
        img = Image.new("RGB", (size, size), GREEN)
        d = ImageDraw.Draw(img)
        initials = "".join(p[0] for p in name.replace(".", "").split()[:2]).upper() or "T"
        font = _font("Bold", int(size * 0.42))
        d.text((size / 2, size / 2), initials, font=font, fill=WHITE, anchor="mm")
    big = Image.new("L", (size * 4, size * 4), 0)  # masque sur-échantillonné : bord du disque lissé
    ImageDraw.Draw(big).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = big.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _card(profile: HandymanProfile, info: Dict, code: str) -> Image.Image:
    W, H = 1011, 638  # 85,6 × 54 mm à 300 dpi (format carte bancaire)
    card = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, W, 96], fill=GREEN)
    d.rectangle([0, 96, W, 104], fill=YELLOW)
    logo = Image.open(ASSETS / "tratra_logo.webp").convert("RGBA").resize((68, 68), Image.LANCZOS)
    card.paste(logo, (24, 14), logo)
    d.text((106, 48), "Tratra", font=_font("Bold", 42), fill=WHITE, anchor="lm")
    d.text((W - 28, 48), "IDENTITÉ PROFESSIONNELLE", font=_font("SemiBold", 21), fill=WHITE, anchor="rm")

    portrait = _portrait(profile, info["display_name"], 190)
    card.paste(portrait, (36, 150), portrait)

    x, max_w = 256, W - 256 - 36 - 300 - 20
    d.text((x, 150), _fit(d, info["display_name"], _font("Bold", 42), max_w), font=_font("Bold", 42), fill=INK)
    trades = ", ".join(info["trades"]) or "Artisan"
    d.text((x, 206), _fit(d, trades, _font("Regular", 26), max_w), font=_font("Regular", 26), fill=ASH)
    d.rounded_rectangle([x, 254, x + 292, 296], radius=21, fill=SOFT)
    d.line([(x + 24, 276), (x + 33, 286), (x + 52, 264)], fill=GREEN_DARK, width=5, joint="curve")  # coche dessinée
    d.text((x + 66, 275), "Identité vérifiée", font=_font("SemiBold", 22), fill=GREEN_DARK, anchor="lm")

    d.text((x, 340), "TRATRA ID", font=_font("Medium", 20), fill=ASH)
    d.text((x, 368), code, font=_font("SemiBold", 48), fill=GREEN_DARK)
    verified_on = info.get("kyc_verified_on")
    if verified_on:
        d.text((x, 438), f"Vérifié par Tratra le {verified_on.strftime('%d/%m/%Y')}", font=_font("Regular", 22), fill=ASH)

    qr = qr_image(verify_url(code)).resize((300, 300), Image.NEAREST)
    qx, qy = W - 36 - 300, 150
    d.rounded_rectangle([qx - 10, qy - 10, qx + 310, qy + 310], radius=16, outline=(226, 232, 240), width=3, fill=WHITE)
    card.paste(qr, (qx, qy))
    d.text((qx + 150, qy + 334), "Scannez pour vérifier", font=_font("Medium", 22), fill=INK, anchor="mm")
    d.text((W / 2, H - 38), verify_url(code).replace("https://", "").replace("http://", ""), font=_font("Regular", 20),
           fill=ASH, anchor="mm")
    d.rectangle([0, H - 12, W, H], fill=GREEN)
    return card


def badge_pdf(profile: HandymanProfile) -> bytes:
    """Badge imprimable (A4, à découper et plastifier). Réservé à un badge ACTIF."""
    if not is_valid(profile):
        raise IdentityError("not_verified", "Le badge imprimable n'est disponible que lorsque votre identité est "
                                            "vérifiée.", 409)
    pro = ensure_id(profile)
    info = holder(profile, full_name=True)
    card = _card(profile, info, pro.code)
    page = Image.new("RGB", (2480, 3508), WHITE)  # A4 à 300 dpi
    d = ImageDraw.Draw(page)
    d.text((1240, 200), "Votre badge Tratra ID", font=_font("Bold", 64), fill=INK, anchor="mm")
    d.text((1240, 290), "Imprimez, découpez suivant le pointillé puis plastifiez.", font=_font("Regular", 36),
           fill=ASH, anchor="mm")
    cx, cy = (2480 - card.width) // 2, 420
    page.paste(card, (cx, cy))
    for x in range(cx - 20, cx + card.width + 21, 24):  # pointillé de découpe
        d.line([(x, cy - 20), (x + 12, cy - 20)], fill=ASH, width=3)
        d.line([(x, cy + card.height + 20), (x + 12, cy + card.height + 20)], fill=ASH, width=3)
    for y in range(cy - 20, cy + card.height + 21, 24):
        d.line([(cx - 20, y), (cx - 20, y + 12)], fill=ASH, width=3)
        d.line([(cx + card.width + 20, y), (cx + card.width + 20, y + 12)], fill=ASH, width=3)
    note = ("Ce badge ne contient aucune donnée sensible : le QR renvoie vers la page de vérification Tratra, qui "
            "indique en temps réel si votre identité professionnelle est valide.")
    d.multiline_text((1240, cy + card.height + 160), "\n".join(_wrap(d, note, _font("Regular", 32), 1500)),
                     font=_font("Regular", 32), fill=ASH, anchor="ma", align="center", spacing=14)
    buf = io.BytesIO()
    page.save(buf, "PDF", resolution=300.0, title=f"Badge Tratra ID {pro.code}", author="Tratra")
    return buf.getvalue()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int):
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
        else:
            yield line
            line = word
    if line:
        yield line
