"""Aides de test partagées (jamais importées par le code de production).

`make_eligible` complète un profil artisan pour qu'il satisfasse TOUTE la règle d'éligibilité
(handy/eligibility.py) : à appeler dans les fixtures des tests qui ont besoin d'un artisan
publié ou réservable. Non destructif : ne remplace pas ce que le test a déjà renseigné
(commune, spécialités, présentation…).
"""
from handy.models import HandymanDocument, ServiceCategory


def make_eligible(profile, *, category=None):
    profile.is_approved = True
    profile.bio = profile.bio or "Plombier depuis dix ans."
    profile.experience_years = profile.experience_years or 10
    profile.photo = profile.photo or "profile_pics/test.jpg"
    profile.commune = profile.commune or "Cocody"
    profile.save()
    if not profile.skills.exists():
        # Catégorie neutre : n'interfère avec aucun filtre de catégorie des tests.
        profile.skills.add(category or ServiceCategory.objects.get_or_create(
            slug="eligibility-skill", defaults={"name": "Spécialité de test", "is_active": False})[0])
    doc, _ = HandymanDocument.objects.get_or_create(
        handyman=profile, document_type="id_card", defaults={"file": "kyc/test.pdf", "status": "approved"})
    if doc.status != "approved":
        doc.status = "approved"
        doc.save(update_fields=["status"])   # enregistrement normal : la copie calculée de l'éligibilité suit (eligibility_sync)
    profile.refresh_from_db(fields=["published"])
    return profile


def make_jpeg(size=(900, 700), color=(200, 90, 40), exif=False) -> bytes:
    """Vrai JPEG (dégradé : décodable, de taille réaliste) ; `exif=True` y ajoute une position GPS pour vérifier son retrait."""
    import io

    from PIL import Image

    img = Image.new("RGB", size, color)
    px = img.load()
    for x in range(0, size[0], 7):
        for y in range(0, size[1], 7):
            px[x, y] = ((x * 3) % 255, (y * 5) % 255, (x + y) % 255)
    out = io.BytesIO()
    if exif:
        ex = Image.Exif()
        ex[0x010F] = "TestCam"
        ex[0x8825] = {1: "N", 2: (5.0, 21.0, 36.0)}
        img.save(out, "JPEG", exif=ex)
    else:
        img.save(out, "JPEG")
    return out.getvalue()


def make_mp4(seconds=5.0, width=720, height=1280, *, rotated=False, timescale=1000, brand=b"isom") -> bytes:
    """Conteneur MP4 minimal VALIDE pour l'analyse (ftyp + moov{mvhd, trak{tkhd, mdia{hdlr}}} + mdat) : durée et dimensions réelles."""
    import struct

    def box(kind, payload=b""):
        return struct.pack(">I4s", 8 + len(payload), kind) + payload

    mvhd = box(b"mvhd", struct.pack(">B3xIIII", 0, 0, 0, timescale, int(seconds * timescale)) + b"\x00" * 80)
    matrix = struct.pack(">9i", 0, 0x10000, 0, -0x10000, 0, 0, 0, 0, 0x40000000) if rotated else \
        struct.pack(">9i", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    # tkhd v0 : version/flags(4) création(4) modif(4) piste(4) réservé(4) durée(4) réservé(8) couche(2) groupe(2) volume(2) réservé(2) matrice(36) l(4) h(4)
    tkhd = box(b"tkhd", struct.pack(">B3xIIIII", 0, 0, 0, 1, 0, int(seconds * timescale)) + b"\x00" * 8 + b"\x00" * 8 + matrix
               + struct.pack(">II", width << 16, height << 16))
    hdlr = box(b"hdlr", struct.pack(">B3xI4s", 0, 0, b"vide") + b"\x00" * 12 + b"video\x00")
    trak = box(b"trak", tkhd + box(b"mdia", hdlr))
    return box(b"ftyp", brand + b"\x00\x00\x02\x00" + b"isomiso2mp41") + box(b"moov", mvhd + trak) + box(b"mdat", b"\x00" * 2048)
