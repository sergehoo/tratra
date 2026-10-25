"""Moteur PDF A4 des contrats, sans dépendance externe : polices Helvetica standard (aucune police embarquée, encodage WinAnsi pour les
accents français), logo officiel en image, QR code vectoriel, en-tête et pied de page sur chaque page, encadrés, tableaux et blocs
insécables, pagination « X/Y ».

Le rendu est DÉTERMINISTE (aucune date de création ni identifiant aléatoire) : les mêmes données donnent le même fichier, donc la même
empreinte SHA-256 — celle que les parties signent et que Tratra scelle (Ed25519, engagements/signing.py). Les flux de contenu ne sont
pas compressés : le texte (dont l'adresse de vérification) reste lisible dans le fichier. Les caractères hors WinAnsi sont convertis
(espaces insécables, flèches…) ou remplacés par « ? »."""
import functools
import hashlib
import re
import unicodedata
import zlib
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

PAGE_W, PAGE_H = 595.28, 841.89          # A4 en points
MARGIN_X = 50.0
CONTENT_TOP = PAGE_H - 92                 # sous l'en-tête
CONTENT_BOTTOM = 86.0                     # au-dessus du pied de page

Color = Tuple[float, float, float]
GREEN: Color = (0.180, 0.545, 0.341)      # vert Tratra #2e8b57
GREEN_DARK: Color = (0.118, 0.420, 0.259)
INK: Color = (0.043, 0.071, 0.063)        # noir Tratra #0b1210
YELLOW: Color = (0.965, 0.788, 0.055)     # jaune Tratra #F6C90E
MUTED: Color = (0.357, 0.400, 0.439)
LINE: Color = (0.835, 0.871, 0.851)
TINT: Color = (0.925, 0.961, 0.937)       # vert très clair (cellules de libellés)
WHITE: Color = (1.0, 1.0, 1.0)

REGULAR, BOLD, ITALIC = "F1", "F2", "F3"

# Largeurs Helvetica (1/1000 em) des caractères ASCII imprimables ; les autres (accents…) prennent la largeur de leur base.
_W = {c: w for c, w in zip(
    " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~",
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
     278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667,
     611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833,
     556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584])}
_EXTRA_W = {"—": 1000, "–": 556, "’": 222, "‘": 222, "«": 556, "»": 556, "…": 1000, "€": 556, "•": 350, "·": 278, "°": 400}
_BOLD_FACTOR = 1.08

# Caractères hors WinAnsi convertis plutôt que remplacés par « ? ».
_TRANSLATE = str.maketrans({" ": " ", " ": " ", " ": " ", " ": " ", "→": "->", "←": "<-", "≥": ">=",
                            "≤": "<=", "≠": "!=", "−": "-", "‑": "-", "✓": "v", "✕": "x", "​": ""})


def clean(text: str) -> str:
    """Typographie : espaces multiples réduits, ponctuation doublée supprimée (« réparations.. » → « réparations. », « ,, », « . , »),
    sans toucher aux points de suspension ni au sens du texte."""
    s = (text or "").translate(_TRANSLATE)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"(?<!\.)\.\s*\.(?!\.)", ".", s)               # « .. » ou « . . » (pas « ... »)
    s = re.sub(r",\s*,+", ",", s)
    s = re.sub(r"[ ]+([,.])(?=\s|$)", r"\1", s)                # « mot , » → « mot, »
    s = re.sub(r"\.,|,\.", ".", s)
    s = re.sub(r";\s*;+", ";", s)
    return "\n".join(line.strip() for line in s.split("\n"))


def width(text: str, size: float, font: str = REGULAR) -> float:
    total = 0
    for ch in text:
        if ch in _W:
            total += _W[ch]
        elif ch in _EXTRA_W:
            total += _EXTRA_W[ch]
        else:
            base = unicodedata.normalize("NFKD", ch)[:1] or ch
            total += _W.get(base, 556)
    return total * size / 1000 * (_BOLD_FACTOR if font == BOLD else 1)


def _encode(text: str) -> bytes:
    raw = text.translate(_TRANSLATE).encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def wrap(text: str, size: float, max_width: float, font: str = REGULAR) -> List[str]:
    """Coupure aux espaces ; un mot plus long que la ligne (empreinte, adresse) est coupé à la lettre plutôt que de déborder."""
    lines: List[str] = []
    for paragraph in (text or "").split("\n"):
        line = ""
        for word in paragraph.split(" "):
            while width(word, size, font) > max_width and len(word) > 1:
                if line:
                    lines.append(line)
                    line = ""
                cut = len(word)
                while cut > 1 and width(word[:cut], size, font) > max_width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            candidate = f"{line} {word}" if line else word
            if not line or width(candidate, size, font) <= max_width:
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


@functools.lru_cache(maxsize=4)
def _logo(path: str, px: int = 120) -> Optional[Tuple[int, int, bytes, bytes]]:
    """Logo officiel → (largeur, hauteur, RVB compressé, alpha compressé) ; None si le fichier est absent (le texte « TRATRA » suffit)."""
    if not path or not Path(path).exists():
        return None
    from PIL import Image

    img = Image.open(path).convert("RGBA").resize((px, px), Image.LANCZOS)
    rgb = img.convert("RGB").tobytes()
    alpha = img.getchannel("A").tobytes()
    return px, px, zlib.compress(rgb, 9), zlib.compress(alpha, 9)


def _rgb(color: Color, stroke: bool = False) -> bytes:
    return b"%.3f %.3f %.3f %s" % (color[0], color[1], color[2], b"RG" if stroke else b"rg")


class Layout:
    """Pages A4 composées de haut en bas : `y` est le haut de la prochaine ligne. Les blocs insécables passent à la page suivante plutôt
    que d'être coupés ; un paragraphe long continue ligne à ligne sur la page suivante."""

    def __init__(self, *, logo_path: str = ""):
        self.pages: List[List[bytes]] = [[]]
        self.left, self.right = MARGIN_X, PAGE_W - MARGIN_X
        self.top, self.bottom = CONTENT_TOP, CONTENT_BOTTOM
        self.y = self.top
        self.logo = _logo(logo_path) if logo_path else None

    # ── Pagination ────────────────────────────────────────────────────────────────────────────────────────────────────
    @property
    def width(self) -> float:
        return self.right - self.left

    def new_page(self) -> None:
        self.pages.append([])
        self.y = self.top

    def room(self) -> float:
        return self.y - self.bottom

    def ensure(self, height: float) -> None:
        """Place libre pour `height` points, sinon page suivante (jamais une page vide de plus)."""
        if height > self.room() and self.y < self.top - 0.5:
            self.new_page()

    def page_break(self) -> None:
        if self.y < self.top - 0.5:
            self.new_page()

    def space(self, h: float) -> None:
        self.y -= h
        if self.y < self.bottom:
            self.new_page()

    # ── Primitives (page courante) ────────────────────────────────────────────────────────────────────────────────────
    def text(self, x: float, baseline: float, s: str, size: float, font: str = REGULAR, color: Color = INK, page: Optional[List[bytes]] = None):
        (self.pages[-1] if page is None else page).append(
            b"BT " + _rgb(color) + b" /" + font.encode() + b" %.2f Tf %.2f %.2f Td (" % (size, x, baseline) + _encode(s) + b") Tj ET")

    def text_right(self, x_right: float, baseline: float, s: str, size: float, font: str = REGULAR, color: Color = INK, page=None):
        self.text(x_right - width(s, size, font), baseline, s, size, font, color, page)

    def rect(self, x: float, y: float, w: float, h: float, fill: Optional[Color] = None, stroke: Optional[Color] = None, lw: float = 0.6,
             page: Optional[List[bytes]] = None):
        ops = (self.pages[-1] if page is None else page)
        parts = [b"q"]
        if fill:
            parts.append(_rgb(fill))
        if stroke:
            parts += [_rgb(stroke, True), b"%.2f w" % lw]
        parts.append(b"%.2f %.2f %.2f %.2f re %s Q" % (x, y, w, h, b"B" if fill and stroke else b"f" if fill else b"S"))
        ops.append(b" ".join(parts))

    def line(self, x1: float, y1: float, x2: float, y2: float, color: Color = LINE, lw: float = 0.6, page=None):
        (self.pages[-1] if page is None else page).append(b"q " + _rgb(color, True) + b" %.2f w %.2f %.2f m %.2f %.2f l S Q" % (lw, x1, y1, x2, y2))

    def image_logo(self, x: float, y: float, size: float, page=None) -> bool:
        if not self.logo:
            return False
        (self.pages[-1] if page is None else page).append(b"q %.2f 0 0 %.2f %.2f %.2f cm /Logo Do Q" % (size, size, x, y))
        return True

    def qr(self, data: str, x: float, y_top: float, size: float, page=None):
        matrix = qr_matrix(data)
        cell = size / len(matrix)
        ops = [b"q 0 0 0 rg"]
        for r, row in enumerate(matrix):
            for c, dark in enumerate(row):
                if dark:
                    ops.append(b"%.2f %.2f %.2f %.2f re" % (x + c * cell, y_top - (r + 1) * cell, cell, cell))
        ops.append(b"f Q")
        (self.pages[-1] if page is None else page).append(b"\n".join(ops))

    # ── Blocs ─────────────────────────────────────────────────────────────────────────────────────────────────────────
    def paragraph(self, s: str, size: float = 10, font: str = REGULAR, color: Color = INK, leading: Optional[float] = None, indent: float = 0,
                  after: float = 4, max_width: Optional[float] = None):
        leading = leading or size * 1.42
        for line in wrap(clean(s), size, (max_width or self.width) - indent, font):
            self.ensure(leading)
            self.text(self.left + indent, self.y - size * 0.82, line, size, font, color)
            self.y -= leading
        self.y -= after

    def heading(self, s: str, level: int = 1, keep_with: float = 42):
        """Titre hiérarchisé, jamais seul en bas de page (gardé avec le début de ce qui suit)."""
        size, color, before, after = {1: (12.5, GREEN_DARK, 14, 8), 2: (10.8, GREEN_DARK, 10, 5), 3: (9.8, INK, 6, 3)}[level]
        lines = wrap(clean(s), size, self.width, BOLD)
        need = before + len(lines) * size * 1.3 + after + keep_with
        if need > self.room():
            self.page_break()
        else:
            self.y -= before
        if level == 1:
            self.rect(self.left, self.y - len(lines) * size * 1.3 - 3, 3, len(lines) * size * 1.3 + 2, fill=YELLOW)
        for line in lines:
            self.text(self.left + (9 if level == 1 else 0), self.y - size * 0.85, line, size, BOLD, color)
            self.y -= size * 1.3
        if level == 1:
            self.line(self.left, self.y - 2, self.right, self.y - 2, LINE, 0.6)
        self.y -= after

    def table(self, rows: Sequence[Tuple[str, str]], label_width: float = 150, size: float = 9.2, pad: float = 5):
        """Tableau libellé / valeur : une ligne n'est jamais coupée entre deux pages (sauf si elle dépasse à elle seule une page)."""
        leading = size * 1.38
        value_width = self.width - label_width - 2 * pad
        for label, value in rows:
            lab = wrap(clean(label), size, label_width - 2 * pad, BOLD)
            val = wrap(clean(value or "—"), size, value_width, REGULAR)
            height = max(len(lab), len(val)) * leading + 2 * pad
            if height <= self.top - self.bottom:
                self.ensure(height)
                self._row(lab, val, height, label_width, size, leading, pad)
            else:                                         # ligne plus haute qu'une page : découpée, libellé répété
                per_page = int((self.top - self.bottom - 2 * pad) // leading)
                for start in range(0, len(val), per_page):
                    chunk = val[start:start + per_page]
                    h = len(chunk) * leading + 2 * pad
                    self.ensure(h)
                    self._row(lab if start == 0 else [f"{lab[0]} (suite)"], chunk, h, label_width, size, leading, pad)

    def _row(self, lab: List[str], val: List[str], height: float, label_width: float, size: float, leading: float, pad: float):
        top = self.y
        self.rect(self.left, top - height, label_width, height, fill=TINT)
        self.rect(self.left, top - height, self.width, height, stroke=LINE, lw=0.5)
        self.line(self.left + label_width, top, self.left + label_width, top - height, LINE, 0.5)
        for i, line in enumerate(lab):
            self.text(self.left + pad, top - pad - size * 0.82 - i * leading, line, size, BOLD, GREEN_DARK)
        for i, line in enumerate(val):
            self.text(self.left + label_width + pad, top - pad - size * 0.82 - i * leading, line, size, REGULAR, INK)
        self.y = top - height

    def boxes(self, boxes: Sequence[Tuple[str, Sequence[Tuple[str, str]]]], gap: float = 12, size: float = 8.6, label_ratio: float = 0.34):
        """Encadrés côte à côte (titre + lignes « libellé | valeur »), de même hauteur, insécables (parties, signatures). Un libellé vide
        donne une valeur sur toute la largeur."""
        n = len(boxes)
        col = (self.width - gap * (n - 1)) / n
        pad, leading, title_h = 7.0, size * 1.34, 19.0
        label_w = col * label_ratio
        prepared = []
        for title, rows in boxes:
            cells = []
            for label, value in rows:
                vw = col - 2 * pad - (label_w if label else 0)
                lab = wrap(clean(label), size - 0.6, label_w - 6, BOLD) if label else []
                vsize = 6.4 if re.fullmatch(r"[0-9a-f]{64}", (value or "").strip()) else size       # empreinte : petit corps, 2 lignes au plus
                val = wrap(clean(value or "—"), vsize, vw, REGULAR)
                cells.append((lab, val, vsize, max(len(lab) * leading, len(val) * (vsize * 1.34 if vsize != size else leading)) + 3))
            prepared.append((title, cells))
        height = title_h + pad + max(sum(h for _, _, _, h in cells) for _, cells in prepared) + pad - 3
        self.ensure(height)
        top = self.y
        for i, (title, cells) in enumerate(prepared):
            x = self.left + i * (col + gap)
            self.rect(x, top - height, col, height, stroke=LINE, lw=0.7)
            self.rect(x, top - title_h, col, title_h, fill=GREEN)
            self.text(x + pad, top - title_h + 6.3, clean(title).upper(), 8.4, BOLD, WHITE)
            y = top - title_h - pad
            for lab, val, vsize, h in cells:
                for j, line in enumerate(lab):
                    self.text(x + pad, y - size * 0.82 - j * leading, line, size - 0.6, BOLD, MUTED)
                vlead = leading if vsize == size else vsize * 1.34
                for j, line in enumerate(val):
                    self.text(x + pad + (label_w if lab else 0), y - vsize * 0.82 - j * vlead, line, vsize, REGULAR, INK)
                y -= h
        self.y = top - height

    # ── Assemblage ────────────────────────────────────────────────────────────────────────────────────────────────────
    def finish(self, decorate: Callable[["Layout", List[bytes], int, int], None]) -> bytes:
        """En-tête et pied de page (qui connaissent « page X/Y »), puis le fichier PDF."""
        n = len(self.pages)
        for i, page in enumerate(self.pages, start=1):
            decorate(self, page, i, n)
        objects: List[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
        for base in (b"Helvetica", b"Helvetica-Bold", b"Helvetica-Oblique"):     # objets 3, 4, 5
            objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /" + base + b" /Encoding /WinAnsiEncoding >>")
        xobjects = b""
        if self.logo:
            w, h, rgb, alpha = self.logo
            objects.append(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceGray /BitsPerComponent 8 "
                           b"/Filter /FlateDecode /Length %d >>\nstream\n" % (w, h, len(alpha)) + alpha + b"\nendstream")
            smask = len(objects)
            objects.append(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                           b"/Filter /FlateDecode /SMask %d 0 R /Length %d >>\nstream\n" % (w, h, smask, len(rgb)) + rgb + b"\nendstream")
            xobjects = b" /XObject << /Logo %d 0 R >>" % len(objects)
        kids = []
        for content in self.pages:
            stream = b"\n".join(content)
            objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
            content_id = len(objects)
            objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >>"
                           % (PAGE_W, PAGE_H) + xobjects + b" >> /Contents %d 0 R >>" % content_id)
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


def page_texts(data: bytes) -> List[str]:
    """Texte de chaque page (contrôles et tests) : chaînes des opérateurs Tj, dans l'ordre de dessin."""
    pages = []
    for stream in re.findall(rb"stream\n(.*?)\nendstream", data, re.S):
        if b" Tj ET" not in stream:
            continue
        strings = re.findall(rb"\(((?:\\.|[^\\)])*)\) Tj", stream)
        pages.append("\n".join(re.sub(rb"\\(.)", rb"\1", s).decode("cp1252") for s in strings))
    return pages


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
