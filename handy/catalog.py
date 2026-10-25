"""Catalogue unique des métiers : arbre, icônes normalisées, offres publiées, charge utile publique (web, application mobile).

Source de vérité = `ServiceCategory` (PostgreSQL) ; aucun catalogue n'est écrit en dur côté web ou mobile.

  FAMILLE    `CatalogFamily` : regroupement de navigation            « Informatique & Numérique »
  MÉTIER     catégorie racine (`parent` vide)                      « Jardinage », « Cuisine », « Nounou »
  PRESTATION sous-catégorie (`parent` renseigné)                    « Entretien de fleurs » sous « Jardinage »
  OFFRE      `Service` publié par un professionnel éligible         comptée dans `offers_count` (directe) et `offers_total` (avec les prestations)

Synonymes (`keywords`) : recherche et « J'ai une panne » (`match`, sans aucune donnée personnelle ni texte conservé).

Règles : un métier ACTIF reste visible même sans offre ; une catégorie désactivée disparaît avec ses prestations ; l'ordre est `position` puis le
nom ; `is_featured` désigne les métiers mis en avant ; les identifiants ne changent jamais."""
import hashlib
import json
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Set

from django.core.cache import cache
from django.db.models import Count
from django.utils import timezone

CACHE_KEY = "handy:catalog:v2"
CACHE_SECONDS = 30

# Vocabulaire d'icônes COMMUN (noms Font Awesome 6, tels que saisis dans l'administration : « fa-solid fa-utensils »).
# Chaque client (web : Lucide ; mobile : Font Awesome) doit savoir dessiner chacune de ces clés ; une clé inconnue donne l'icône par défaut.
ICON_KEYS = (
    # bricolage, construction, maison
    "wrench", "screwdriver-wrench", "screwdriver", "hammer", "toolbox", "paint-roller", "paintbrush", "brush", "faucet", "faucet-drip", "droplet", "shower", "bath",
    "toilet", "bolt", "plug", "lightbulb", "fire", "fire-flame-curved", "temperature-half", "snowflake", "wind", "fan", "key", "lock", "door-open", "door-closed",
    "house", "house-chimney", "house-chimney-crack", "building", "warehouse", "trowel", "trowel-bricks", "ruler-combined", "border-all", "layer-group", "chair",
    "couch", "bed", "window-maximize", "igloo", "helmet-safety", "gear", "gears",
    # cuisine et restauration
    "utensils", "kitchen-set", "bowl-food", "mug-hot", "burger", "pizza-slice", "cake-candles", "blender", "jar", "wine-glass", "cookie-bite", "bread-slice",
    "carrot", "fish", "egg", "ice-cream",
    # personnes, enfants, santé
    "user-nurse", "baby", "baby-carriage", "child", "children", "person", "people-group", "user-group", "hands-holding-child", "hand-holding-heart", "heart",
    "heart-pulse", "stethoscope", "wheelchair", "user-doctor",
    # entretien et ménage
    "broom", "soap", "spray-can-sparkles", "shirt", "jug-detergent", "trash", "trash-can", "recycle", "dumpster",
    # transport
    "truck", "truck-ramp-box", "truck-fast", "car", "car-side", "taxi", "bus", "motorcycle", "bicycle", "gas-pump", "road", "van-shuttle",
    # numérique
    "laptop", "laptop-code", "computer", "mobile-screen-button", "wifi", "camera", "video", "tv", "headphones", "print",
    "phone", "cloud", "server", "bullhorn", "tablet-screen-button", "radio", "satellite-dish", "network-wired", "microchip", "code", "house-signal",
    # réparation et équipements
    "shoe-prints", "industry", "truck-pickup", "car-battery", "bug",
    # enseignement, loisirs, événements
    "music", "guitar", "book", "graduation-cap", "chalkboard-user", "pen", "palette", "camera-retro", "futbol", "dumbbell", "champagne-glasses", "gift", "ring",
    # animaux, jardin, extérieur
    "paw", "dog", "cat", "seedling", "leaf", "tree", "tractor", "sun", "water-ladder", "person-swimming", "spa",
    # services divers
    "handshake", "handshake-angle", "bell-concierge", "shield-halved", "user-shield", "box", "boxes-stacked", "clipboard-check", "scissors", "glass-water",
    "store", "briefcase", "money-bill-wave", "tag", "star",
)
DEFAULT_ICON_KEY = "screwdriver-wrench"

# Anciens noms Font Awesome 5 (encore présents dans la base) → nom Font Awesome 6 du vocabulaire.
ALIASES = {
    "home": "house", "tools": "screwdriver-wrench", "trash-alt": "trash-can", "house-damage": "house-chimney-crack", "swimming-pool": "water-ladder",
    "truck-moving": "truck-ramp-box", "border-style": "border-all", "tint": "droplet", "paint-brush": "paintbrush", "birthday-cake": "cake-candles",
    "hard-hat": "helmet-safety", "chalkboard-teacher": "chalkboard-user", "user-friends": "user-group", "hands-helping": "handshake-angle",
    "concierge-bell": "bell-concierge", "mobile-alt": "mobile-screen-button", "car-alt": "car-side", "shield-alt": "shield-halved", "glass-martini": "wine-glass",
    "broadcast-tower": "wifi", "baby-bottle": "baby", "fire-alt": "fire-flame-curved", "thermometer-half": "temperature-half", "hand-holding-heart": "hand-holding-heart",
    "money-bill-alt": "money-bill-wave", "tools-alt": "screwdriver-wrench", "user-md": "user-doctor", "swimmer": "person-swimming", "pizza": "pizza-slice", "hamburger": "burger", "coffee": "mug-hot",
}

# Icône par défaut d'une catégorie SANS icône renseignée (jamais écrite en base) : une seule table, côté serveur.
DEFAULT_ICON_BY_SLUG = {
    "plomberie": "faucet", "electricite": "bolt", "climatisation": "snowflake", "chauffage": "fire", "serrurerie": "key", "peinture": "paint-roller",
    "bricolage": "screwdriver-wrench", "montage-meuble": "couch", "menage": "broom", "nettoyage": "broom", "nettoyage-apres-travaux": "spray-can-sparkles",
    "jardinage": "seedling", "paysagisme": "leaf", "entretien-piscine": "water-ladder", "mecanique-auto": "car-side", "carrosserie": "car", "lavage-auto": "car",
    "assistance-informatique": "laptop-code", "reparation-ordinateur": "laptop-code", "reparation-smartphone": "mobile-screen-button", "demenagement": "truck",
    "debarras": "trash-can", "garde-denfants": "baby", "garde-danimaux": "paw", "service-traiteur": "utensils", "surveillance-maison": "shield-halved",
    "cours-particulier": "book", "chauffeur-prive": "car", "maconnerie": "trowel-bricks", "carrelage": "border-all", "toiture": "house-chimney", "platrerie": "trowel",
    "isolation": "igloo", "cloture": "layer-group", "terrasse": "border-all", "menuiserie": "hammer", "ebenisterie": "chair", "ferronnerie": "hammer",
    "pose-parquet": "border-all", "vitrerie": "window-maximize", "sol-pvc": "border-all", "installation-electromenager": "blender",
    "reparation-electromenager": "blender", "animation-evenement": "music", "decoration-evenement": "champagne-glasses", "cuisine": "utensils", "nounou": "baby",
}

_STYLE = re.compile(r"^fa-(solid|regular|brands|light|thin|duotone|sharp|fw|lg|xs|sm|[0-9]+x|spin|pulse|beat|fade|bounce|flip|shake)$")


def icon_key(raw: Optional[str], slug: str = "") -> Optional[str]:
    """Clé d'icône normalisée : « fa-solid fa-utensils » → « utensils », « fas fa-home » → « house ». Sans icône : valeur par défaut du slug, sinon None."""
    tokens = (raw or "").lower().split()
    names = [t[3:] for t in tokens if t.startswith("fa-") and not _STYLE.match(t)]
    if not names and len(tokens) == 1 and re.fullmatch(r"[a-z0-9-]+", tokens[0]) and not tokens[0].startswith("fa-") and not re.fullmatch(r"fa[srbltd]?", tokens[0]):
        names = [tokens[0]]
    key = ALIASES.get(names[-1], names[-1]) if names else None
    return key or DEFAULT_ICON_BY_SLUG.get(slug)


def icon_known(key: Optional[str]) -> bool:
    return bool(key) and key in ICON_KEYS


def kind_of(parent_id: Optional[int]) -> str:
    return "trade" if parent_id is None else "service"


def _plain(text: str) -> str:
    """Nom sans accents ni casse : « Élagage » se range avec les E, comme en français (même ordre sur tous les clients)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).casefold()


def _sort_key(row: Dict):
    return (row["position"], _plain(row["name"]), row["id"])


def _load_rows() -> List[Dict]:
    from handy.models import ServiceCategory

    return list(ServiceCategory.objects.values("id", "name", "slug", "description", "icon", "is_active", "parent_id", "position", "is_featured",
                                               "family_id", "keywords"))


def keywords_of(raw: Optional[str]) -> List[str]:
    """Synonymes saisis dans l'administration (« frigo, ne refroidit plus ») → liste propre, sans doublon."""
    out, seen = [], set()
    for k in (raw or "").replace("\n", ",").split(","):
        k = k.strip()
        if k and _plain(k) not in seen:
            seen.add(_plain(k))
            out.append(k)
    return out


def _direct_offers() -> Dict[int, int]:
    """Offres PUBLIÉES par catégorie : services actifs d'artisans éligibles (même règle que la recherche publique)."""
    from handy.eligibility import publishable_user_ids
    from handy.models import Service

    rows = Service.objects.filter(is_active=True, handyman_id__in=publishable_user_ids()).values("category_id").annotate(n=Count("id")).order_by()
    return {r["category_id"]: r["n"] for r in rows}


def build_payload() -> Dict:
    """Arbre public complet, à plat et dans l'ordre d'affichage (métier, puis ses prestations), catégories ACTIVES seulement."""
    rows = _load_rows()
    children: Dict[Optional[int], List[Dict]] = {}
    for row in rows:
        children.setdefault(row["parent_id"], []).append(row)
    for siblings in children.values():
        siblings.sort(key=_sort_key)
    direct = _direct_offers()
    items: List[Dict] = []

    from handy.models import CatalogFamily

    families = {f["id"]: f for f in CatalogFamily.objects.filter(is_active=True).values("id", "name", "slug", "description", "icon", "keywords", "position")}

    def visit(row: Dict, trade_id: int, depth: int, family_id: Optional[int]) -> int:
        item = {
            "id": row["id"], "name": row["name"], "slug": row["slug"], "description": row["description"] or "", "icon": row["icon"] or None,
            "icon_key": icon_key(row["icon"], row["slug"]), "parent": row["parent_id"], "trade": trade_id, "kind": kind_of(row["parent_id"]), "depth": depth,
            "family": family_id, "keywords": keywords_of(row["keywords"]),
            "position": row["position"], "order": len(items), "is_featured": bool(row["is_featured"]), "is_active": True,
            "offers_count": direct.get(row["id"], 0), "offers_total": 0, "prestations_count": 0,
        }
        items.append(item)
        total = item["offers_count"]
        for child in children.get(row["id"], []):
            if child["is_active"]:
                item["prestations_count"] += 1
                total += visit(child, trade_id, depth + 1, family_id)
        item["offers_total"] = total
        item["services_count"] = total            # alias historique de la liste /categories/ (offres publiées)
        return total

    for root in children.get(None, []):
        if root["is_active"]:
            family_id = root["family_id"] if root["family_id"] in families else None      # famille masquée : métier « sans famille »
            visit(root, root["id"], 0, family_id)
    # Familles de navigation : seulement celles qui contiennent au moins un métier visible, dans leur ordre ; le reste = « autres métiers ».
    trades_by_family: Dict[int, List[Dict]] = {}
    for item in items:
        if item["kind"] == "trade" and item["family"] is not None:
            trades_by_family.setdefault(item["family"], []).append(item)
    family_items = []
    for f in sorted(families.values(), key=lambda f: (f["position"], _plain(f["name"]), f["id"])):
        members = trades_by_family.get(f["id"])
        if members:
            family_items.append({"id": f["id"], "name": f["name"], "slug": f["slug"], "description": f["description"] or "",
                                 "icon_key": icon_key(f["icon"], ""), "keywords": keywords_of(f["keywords"]), "position": f["position"],
                                 "order": len(family_items), "trades": [m["id"] for m in members],
                                 "offers_total": sum(m["offers_total"] for m in members)})
    body = {"results": items, "families": family_items}
    digest = hashlib.sha1(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return {"count": len(items), "next": None, "previous": None, "version": digest, "generated_at": timezone.now().isoformat(), **body}


def get_payload() -> Dict:
    payload = cache.get(CACHE_KEY)
    if payload is None:
        payload = build_payload()
        cache.set(CACHE_KEY, payload, CACHE_SECONDS)
    return payload


def invalidate() -> None:
    cache.delete(CACHE_KEY)


def with_descendants(ids: Iterable[int]) -> Set[int]:
    """Identifiants demandés + toutes leurs prestations ACTIVES : choisir un métier couvre ses prestations."""
    wanted = {int(i) for i in ids}
    if not wanted:
        return wanted
    from handy.models import ServiceCategory

    children: Dict[Optional[int], List[int]] = {}
    for pk, parent_id in ServiceCategory.objects.filter(is_active=True).values_list("id", "parent_id"):
        children.setdefault(parent_id, []).append(pk)
    found, stack = set(wanted), list(wanted)
    while stack:
        for child in children.get(stack.pop(), []):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def family_trade_ids(family) -> Set[int]:
    """Métiers ACTIFS d'une famille (identifiant ou slug), pour les filtres de recherche ; vide si la famille est inconnue ou masquée."""
    from handy.models import ServiceCategory

    raw = str(family or "").strip()
    if not raw:
        return set()
    lookup = {"family_id": int(raw)} if raw.isdigit() else {"family__slug": raw}
    return set(ServiceCategory.objects.filter(parent__isnull=True, is_active=True, family__is_active=True, **lookup).values_list("id", flat=True))


# ── « J'ai une panne » : du texte libre du client aux prestations et métiers pertinents ─────────────────────────────

# Mots sans valeur pour reconnaître une panne (le texte n'est ni conservé ni journalisé).
STOPWORDS = frozenset("""
a ai as au aux avec avoir c ca ce ces cet cette chez comme d dans de des depuis deux donc du elle elles en est et etre eu fait faire fais
fois hier il ils j je jour jours l la le les leur leurs lui m ma mais me mes moi mon n ne ni nos notre nous on ou par pas peu plus pour pourquoi
qu quand que quel quelle qui quoi s sa sans se ses si son sont suis sur t ta te tes toi ton tous tout toute tres trop tu un une vos votre vous y
aujourd hui maintenant matin soir besoin aide svp merci bonjour bonsoir urgent urgence rapidement vite probleme problemes panne pannes marche
marcher fonctionne fonctionner veux voudrais cherche chercher quelqu personne peut pouvez faut
""".split())


def _tokens(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+", _plain(text))
    return [_stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


def _stem(word: str) -> str:
    """Racine grossière (pluriels, féminins courants) : « fuites » = « fuite », « cassee » = « casse »."""
    for suffix in ("ees", "es", "ee", "s", "x"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(text: str) -> List[str]:
    """Mots utiles d'un texte (sans accents, mots vides retirés, racines grossières) — même règle que « J'ai une panne »."""
    return _tokens(text)


def related(term: str, word: str) -> bool:
    """Même mot ou même racine (préfixe commun de 5 lettres au moins) : « refroidit » ~ « refroidir »."""
    return term == word or (len(term) >= 5 and len(word) >= 5 and (term.startswith(word) or word.startswith(term)))


def category_terms(category) -> Set[str]:
    """Vocabulaire d'un métier ou d'une prestation : noms et synonymes de la catégorie, de son métier et (pour un métier) de ses prestations."""
    from handy.models import ServiceCategory

    if category is None:
        return set()
    nodes = [category]
    if category.parent_id:
        nodes.append(category.parent)
    else:
        nodes += list(ServiceCategory.objects.filter(parent_id=category.pk, is_active=True))
    vocab: Set[str] = set()
    for node in nodes:
        vocab.update(_tokens(node.name))
        for k in keywords_of(getattr(node, "keywords", "")):
            vocab.update(_tokens(k))
    return vocab


def _phrases(row: Dict) -> List[str]:
    return [row["name"], *row.get("keywords", [])]


def match(text: str, limit: int = 6) -> Dict:
    """Prestations (et métiers) correspondant à une description libre : « mon frigo ne refroidit plus » → Réparation de réfrigérateur.

    Score déterministe par COUVERTURE : chaque mot utile du client compte une fois par catégorie s'il apparaît (même mot ou même racine) dans
    son nom ou ses synonymes ; l'expression entière la plus longue retrouvée telle quelle (« ne refroidit plus », « écran cassé ») ajoute un
    bonus. Des synonymes redondants n'augmentent donc pas le score. À score égal, une prestation passe avant son métier."""
    wanted = _tokens(text)
    if not wanted:
        return {"query_terms": [], "results": [], "trades": []}
    plain_text = " " + " ".join(wanted) + " "          # mots utiles du client, dans l'ordre : « voiture ne démarre pas » → « voiture demarre »
    wanted_set = set(wanted)
    payload = get_payload()
    by_id = {row["id"]: row for row in payload["results"]}

    def same(term: str, word: str) -> bool:
        return term == word or (len(term) >= 5 and len(word) >= 5 and (term.startswith(word) or word.startswith(term)))

    def evaluate(row: Dict):
        covered, bonus, hits = set(), 0, []
        for phrase in _phrases(row):
            terms = _tokens(phrase)
            if not terms:
                continue
            matched = {w for w in wanted_set if any(same(t, w) for t in terms)}
            if len(terms) > 1 and (" " + " ".join(terms) + " ") in plain_text:
                bonus = max(bonus, 2 * len(terms))
            elif not matched or (len(terms) > 1 and len(matched) < max(1, len(terms) // 2)):
                continue
            covered |= matched
            hits.append(phrase)
        return covered, bonus, hits

    evaluated = {row["id"]: evaluate(row) for row in payload["results"]}
    scored = []
    for row in payload["results"]:
        covered, bonus, hits = evaluated[row["id"]]
        if not covered:
            continue
        score = 1.5 * len(covered) + bonus
        if row["kind"] == "service":
            # Contexte du métier : « écran cassé du TÉLÉPHONE » départage l'écran de téléphone et l'écran de PC portable.
            score += 0.25 + 0.75 * len(evaluated.get(row["trade"], (set(), 0, []))[0] - covered)
        scored.append((score, row, hits))
    scored.sort(key=lambda x: (-x[0], x[1]["order"]))
    results, trades = [], []
    for score, row, hits in scored[:limit]:
        trade = by_id.get(row["trade"]) or row
        results.append({"id": row["id"], "name": row["name"], "slug": row["slug"], "kind": row["kind"], "icon_key": row["icon_key"] or trade.get("icon_key"),
                        "trade": trade["id"], "trade_name": trade["name"], "trade_slug": trade["slug"], "family": row.get("family"),
                        "offers_total": row["offers_total"], "score": round(score, 2), "matched": hits[:3]})
        if trade["id"] not in trades:
            trades.append(trade["id"])
    return {"query_terms": wanted[:12], "results": results, "trades": trades}
