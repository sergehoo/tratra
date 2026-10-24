"""Document PDF d'un contrat (texte seul), sans dépendance : police Helvetica standard (aucune police embarquée), encodage WinAnsi
(accents français, guillemets, tirets), coupure des lignes et des pages, pied de page « page n / N » et empreinte des conditions.

Le rendu est DÉTERMINISTE (aucune date de création ni identifiant aléatoire) : les mêmes conditions donnent le même fichier, donc la
même empreinte SHA-256 — c'est elle que chaque partie signe. Les caractères hors WinAnsi sont remplacés par « ? »."""
import hashlib
from typing import Iterable, List, Tuple

PAGE_W, PAGE_H = 595.28, 841.89          # A4 en points
MARGIN_X, MARGIN_TOP, MARGIN_BOTTOM = 56, 64, 64
# Largeurs Helvetica (1/1000 em) des caractères ASCII imprimables ; les autres (accents…) prennent la largeur de leur base.
_W = {c: w for c, w in zip(
    " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~",
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
     278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667,
     611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
     556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584])}
_BOLD_FACTOR = 1.06


def _width(text: str, size: float, bold: bool = False) -> float:
    import unicodedata

    total = 0
    for ch in text:
        base = unicodedata.normalize("NFKD", ch)[:1] or ch
        total += _W.get(ch, _W.get(base, 556))
    return total * size / 1000 * (_BOLD_FACTOR if bold else 1)


def _encode(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _wrap(text: str, size: float, width: float, bold: bool = False) -> List[str]:
    lines: List[str] = []
    for paragraph in (text or "").split("\n"):
        words, line = paragraph.split(" "), ""
        for word in words:
            candidate = f"{line} {word}".strip() if line else word
            if _width(candidate, size, bold) <= width or not line:
                line = candidate
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def qr_matrix(data: str) -> List[List[bool]]:
    """Modules d'un QR code (correction M, marge de 2 modules) pour le dessiner en vectoriel dans le PDF."""
    import qrcode

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    return qr.get_matrix()


def _qr_ops(matrix: List[List[bool]], x: float, y_top: float, size: float) -> bytes:
    cell = size / len(matrix)
    ops = [b"0 0 0 rg"]
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                ops.append(b"%.2f %.2f %.2f %.2f re" % (x + c * cell, y_top - (r + 1) * cell, cell, cell))
    ops.append(b"f")
    return b"\n".join(ops)


def render(title: str, blocks: Iterable[Tuple[str, str]], footer: str = "", qr: str = "", qr_caption: str = "") -> bytes:
    """`blocks` : suite de (style, texte) avec style « h1 », « h2 », « p » ou « small ». `qr` : adresse de vérification dessinée en
    QR code en haut à droite de la première page (et le texte des lignes de tête s'arrête avant). Renvoie les octets du PDF."""
    styles = {"h1": (16, True, 10), "h2": (12, True, 6), "p": (10, False, 4), "small": (8, False, 3)}
    full_width = PAGE_W - 2 * MARGIN_X
    qr_size = 92.0
    pages: List[List[bytes]] = [[]]
    y = PAGE_H - MARGIN_TOP
    qr_bottom = PAGE_H - MARGIN_TOP - qr_size - 14 if qr else PAGE_H
    if qr:
        pages[0].append(_qr_ops(qr_matrix(qr), PAGE_W - MARGIN_X - qr_size, PAGE_H - MARGIN_TOP, qr_size))
        if qr_caption:
            cap = _encode(qr_caption)
            pages[0].append(b"BT /F1 6.5 Tf %.2f %.2f Td (" % (PAGE_W - MARGIN_X - qr_size, PAGE_H - MARGIN_TOP - qr_size - 9) + cap + b") Tj ET")

    def emit(line: str, size: float, bold: bool):
        nonlocal y
        if y - size < MARGIN_BOTTOM:
            pages.append([])
            y = PAGE_H - MARGIN_TOP
        font = b"/F2" if bold else b"/F1"
        pages[-1].append(b"BT " + font + b" %.1f Tf %.2f %.2f Td (" % (size, MARGIN_X, y - size) + _encode(line) + b") Tj ET")
        y -= size * 1.35

    for style, text in [("h1", title), *blocks]:
        size, bold, space = styles.get(style, styles["p"])
        width = full_width - (qr_size + 16 if len(pages) == 1 and y > qr_bottom else 0)   # le texte contourne le QR code
        for line in _wrap(text, size, width, bold):
            emit(line, size, bold)
        y -= space
    n = len(pages)
    objects: List[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    fonts = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    fonts_bold = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"
    objects += [fonts, fonts_bold]                                         # objets 3 et 4
    kids = []
    for i, content in enumerate(pages, start=1):
        foot = f"{footer} — page {i}/{n}" if footer else f"Page {i}/{n}"
        content = content + [b"BT /F1 7 Tf %.2f %.2f Td (" % (MARGIN_X, MARGIN_BOTTOM / 2) + _encode(foot) + b") Tj ET"]
        stream = b"\n".join(content)
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_id = len(objects)
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                       b"/Contents %d 0 R >>" % (PAGE_W, PAGE_H, content_id))
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % n
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
