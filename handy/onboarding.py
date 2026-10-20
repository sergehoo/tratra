"""« Inscription accompagnée » : le même compte unique et les mêmes règles que l'inscription classique, présentés question par question.

- Questions configurées dans l'administration (`OnboardingQuestion`), choisies selon le métier ; réponses en gros boutons.
- Les réponses sont enregistrées (`ProOnboarding`) pour reprendre plus tard, sur n'importe quel appareil, puis APPLIQUÉES aux modèles
  existants : profil professionnel (`HandymanProfile`) et une offre (`Service`) rédigée à partir des réponses. Aucun second profil.
- Rien n'est publié avant l'éligibilité (`handy.eligibility`) : identité vérifiée par l'équipe et validation professionnelle.
- Un texte proposé (présentation, description de l'offre) n'est remplacé que s'il n'a pas été retouché par l'utilisateur ; un champ déjà
  rempli par ailleurs (parcours classique) n'est jamais écrasé.
"""
import re
import unicodedata
from typing import Dict, List, Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from handy.eligibility import experience_declared
from handy.models import HandymanProfile, OnboardingQuestion, ProOnboarding, Service, ServiceCategory

# Communes proposées en boutons (Abidjan) ; « Autre » permet de saisir une autre ville.
COMMUNES = ["Abobo", "Adjamé", "Anyama", "Attécoubé", "Bingerville", "Cocody", "Koumassi", "Marcory", "Plateau", "Port-Bouët",
            "Songon", "Treichville", "Yopougon"]

DAY_LABELS = {"monday": "lundi", "tuesday": "mardi", "wednesday": "mercredi", "thursday": "jeudi", "friday": "vendredi",
              "saturday": "samedi", "sunday": "dimanche"}
SLOT_LABELS = {"morning": "le matin", "afternoon": "l’après-midi", "evening": "le soir"}
UNIT_LABELS = {"hour": "de l’heure", "day": "par jour", "month": "par mois", "job": "par intervention"}
SINGLE_TARGETS = {"experience", "price", "days", "slots"}         # une question de métier remplace la question commune de même cible

# Étapes du parcours (affichage de la progression et « Continuer »).
JOURNEY = [
    ("trade", "Votre métier"),
    ("zone", "Votre quartier"),
    ("questions", "Vos réponses"),
    ("account", "Votre compte"),
    ("phone", "Votre téléphone"),
    ("offer", "Votre annonce"),
    ("photo", "Votre photo"),
    ("identity", "Votre identité"),
    ("approval", "Validation par l’équipe Tratra"),
]


class OnboardingError(Exception):
    def __init__(self, code: str, detail: str, status: int = 400):
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    return re.sub(r"[^a-z0-9]+", " ", "".join(c for c in text if unicodedata.category(c) != "Mn")).strip()


def _root(category: Optional[ServiceCategory]) -> Optional[ServiceCategory]:
    seen = set()
    while category is not None and category.parent_id and category.pk not in seen:
        seen.add(category.pk)
        category = category.parent
    return category


def questions_for(trade: Optional[ServiceCategory]) -> List[OnboardingQuestion]:
    """Questions du métier, dans l'ordre : liées au métier, puis par mots-clés, puis communes (une question de métier remplace la
    question commune de même cible pour l'expérience, le tarif, les jours et les moments)."""
    qs = list(OnboardingQuestion.objects.filter(is_active=True).prefetch_related("trades"))
    root = _root(trade)
    haystack = f" {_fold(root.name)} {_fold(root.slug)} " if root else ""
    specific, common = [], []
    for q in qs:
        linked = {t.pk for t in q.trades.all()}
        if linked:
            if root is not None and (root.pk in linked or (trade is not None and trade.pk in linked)):
                specific.append(q)
            continue
        words = [_fold(w) for w in q.trade_keywords.split(",") if _fold(w)]
        if words:
            if haystack and any(f" {w} " in haystack or (len(w) > 4 and w in haystack) for w in words):
                specific.append(q)
            continue
        common.append(q)
    covered = {q.target for q in specific if q.target in SINGLE_TARGETS}
    chosen = specific + [q for q in common if q.target not in covered]
    return sorted(chosen, key=lambda q: (q.position, q.pk))


# Champs publics d'une réponse : libellé, illustration, et de quoi rédiger l'aperçu de l'annonce sur le téléphone (phrase, années, tarif).
OPTION_FIELDS = ("value", "label", "emoji", "phrase", "years", "amount", "unit")


def question_payload(q: OnboardingQuestion) -> Dict:
    return {"key": q.key, "text": q.text, "help": q.help_text, "kind": q.kind, "target": q.target, "required": q.required,
            "options": [{k: v for k, v in o.items() if k in OPTION_FIELDS} for o in (q.options or []) if isinstance(o, dict)]}


def config(trade_id) -> Dict:
    """Configuration publique du parcours pour un métier : prestations, questions, communes (aucune donnée personnelle)."""
    trade = ServiceCategory.objects.filter(pk=trade_id, is_active=True).select_related("parent").first() if trade_id else None
    if trade is None:
        raise OnboardingError("unknown_trade", "Métier introuvable.", 404)
    root = _root(trade)
    prestations = ServiceCategory.objects.filter(parent=root, is_active=True).order_by("position", "name")
    return {
        "trade": {"id": root.pk, "name": root.name, "min_experience_years": root.min_experience_years},
        "prestations": [{"id": c.pk, "name": c.name, "min_experience_years": c.min_experience_years} for c in prestations],
        "questions": [question_payload(q) for q in questions_for(root)],
        "communes": COMMUNES,
        "journey": [{"key": k, "label": label} for k, label in JOURNEY],
    }


# ═══ Réponses ══════════════════════════════════════════════════════════════════════════════════════════════════════════

def _clean_answers(trade, raw) -> Dict:
    """Ne garde que les réponses aux questions du métier, avec des valeurs proposées (jamais de texte libre)."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for q in questions_for(trade):
        allowed = {str(o.get("value")) for o in (q.options or []) if isinstance(o, dict)}
        value = raw.get(q.key)
        if q.kind == "multi":
            values = [str(v) for v in (value if isinstance(value, list) else []) if str(v) in allowed]
            if values:
                out[q.key] = list(dict.fromkeys(values))
        elif value is not None and str(value) in allowed:
            out[q.key] = str(value)
    return out


def _complete(ob: ProOnboarding) -> Dict[str, bool]:
    required = [q for q in questions_for(ob.trade) if q.required] if ob.trade_id else []
    return {
        "trade": ob.trade_id is not None,
        "zone": bool(ob.commune.strip()),
        "questions": ob.trade_id is not None and all(q.key in ob.answers for q in required),
    }


def onboarding_for(user) -> ProOnboarding:
    ob, _ = ProOnboarding.objects.get_or_create(user=user)
    return ob


@transaction.atomic
def save(user, data: Dict) -> Dict:
    """Enregistre ce que le parcours a recueilli (avant comme après la création du compte : rien n'est perdu)."""
    ob = ProOnboarding.objects.select_for_update().get(pk=onboarding_for(user).pk)
    if "trade" in data:
        trade = ServiceCategory.objects.filter(pk=data.get("trade"), is_active=True).first() if data.get("trade") else None
        root = _root(trade)
        if data.get("trade") and root is None:
            raise OnboardingError("unknown_trade", "Métier introuvable.")
        if root is not None and root.pk != ob.trade_id:
            ob.prestations, ob.answers = [], {}                  # autre métier : ses prestations et ses questions changent
        ob.trade = root
    if "prestations" in data and ob.trade_id:
        allowed = set(ServiceCategory.objects.filter(parent_id=ob.trade_id, is_active=True).values_list("pk", flat=True))
        ob.prestations = [int(p) for p in (data.get("prestations") or []) if str(p).isdigit() and int(p) in allowed]
    if "commune" in data:
        ob.commune = str(data.get("commune") or "").strip()[:100]
    if "quartier" in data:
        ob.quartier = str(data.get("quartier") or "").strip()[:100]
    if "answers" in data and ob.trade_id:
        ob.answers = {**ob.answers, **_clean_answers(ob.trade, data.get("answers"))}
        ob.answers = _clean_answers(ob.trade, ob.answers)
    if "step" in data:
        ob.step = str(data.get("step") or "")[:30]
    if data.get("path") in dict(ProOnboarding.PATHS):
        ob.path = data["path"]
    ob.save()
    return state(user)


# ═══ Textes proposés (sans IA : phrases construites à partir des réponses) ═════════════════════════════════════════════

def _options(ob: ProOnboarding) -> List[tuple]:
    """(question, options choisies) dans l'ordre du parcours."""
    out = []
    for q in questions_for(ob.trade):
        value = ob.answers.get(q.key)
        values = value if isinstance(value, list) else ([value] if value is not None else [])
        chosen = [o for o in (q.options or []) if isinstance(o, dict) and str(o.get("value")) in values]
        if chosen:
            out.append((q, chosen))
    return out


def _join(items: List[str]) -> str:
    items = [i for i in items if i]
    return items[0] if len(items) == 1 else (", ".join(items[:-1]) + " et " + items[-1] if items else "")


def _days(days: List[str]) -> str:
    order = list(DAY_LABELS)
    days = sorted(days, key=order.index)
    if len(days) == 7:
        return "tous les jours"
    if days == order[:5]:
        return "du lundi au vendredi"
    if days == order[:6]:
        return "du lundi au samedi"
    return _join([DAY_LABELS[d] for d in days])


def profile_values(ob: ProOnboarding) -> Dict:
    """Ce que les réponses donnent pour le profil et l'offre (pur : aucun enregistrement)."""
    v = {"experience": None, "days": [], "slots": [], "strengths": [], "infos": [], "price": None}
    for q, chosen in _options(ob):
        if q.target == "experience":
            v["experience"] = declared_experience(chosen[0])
        elif q.target == "days":
            v["days"] = [str(o["value"]) for o in chosen if str(o["value"]) in DAY_LABELS]
        elif q.target == "slots":
            v["slots"] = [str(o["value"]) for o in chosen if str(o["value"]) in SLOT_LABELS]
        elif q.target == "strengths":
            v["strengths"] += [o.get("phrase") or o.get("label", "").lower() for o in chosen]
        elif q.target == "info":
            v["infos"] += [o.get("phrase") or o.get("label", "") for o in chosen]
        elif q.target == "price":
            v["price"] = chosen[0]
    return v


def declared_experience(option: Dict) -> Dict:
    """Déclaration EXACTE : libellé choisi (« Moins d’un an ») et années = borne basse de la tranche (jamais arrondies vers le haut)."""
    years = option.get("years")
    if years is None:
        value = str(option.get("value") or "")
        years = int(value) if value.isdigit() else 0
    return {"years": max(0, int(years)), "label": str(option.get("label") or "").strip()[:60]}


def _experience_sentence(experience: Optional[Dict]) -> str:
    return f"Expérience : {experience['label'][:1].lower()}{experience['label'][1:]}." if experience and experience["label"] else ""


def _place(ob) -> str:
    return f"{ob.commune}{f' ({ob.quartier})' if ob.quartier else ''}"


def offer_draft(ob: ProOnboarding) -> Dict:
    """Annonce proposée : titre, description, tarif — affichée telle quelle avant la création du compte (aperçu)."""
    v = profile_values(ob)
    trade = ob.trade.name if ob.trade_id else "Services"
    prestations = list(ServiceCategory.objects.filter(pk__in=ob.prestations).order_by("position", "name").values_list("name", flat=True))
    label = prestations[0] if len(prestations) == 1 else trade
    title = f"{label} à {ob.commune}" if ob.commune else label
    lines = [f"Je propose mes services de {trade.lower()} à {_place(ob)}." if ob.commune else f"Je propose mes services de {trade.lower()}."]
    if len(prestations) > 1:
        lines.append(f"Prestations : {_join([p.lower() for p in prestations])}.")
    if v["strengths"]:
        lines.append(f"Ce que je fais : {_join(v['strengths'])}.")
    if v["infos"]:
        lines.append(f"{_join(v['infos']).capitalize()}.")
    if v["days"] or v["slots"]:
        when = " ".join(x for x in [_days(v["days"]) if v["days"] else "", _join([SLOT_LABELS[s] for s in v["slots"]])] if x)
        lines.append(f"Disponible {when}.")
    if _experience_sentence(v["experience"]):
        lines.append(_experience_sentence(v["experience"]))
    price = v["price"] or {}
    unit, amount = price.get("unit"), price.get("amount")
    if unit in ("day", "month") and amount:
        lines.append(f"Tarif souhaité : {int(amount):,} FCFA {UNIT_LABELS[unit]} (à discuter).".replace(",", " "))
    if unit == "quote":
        lines.append("Prix à discuter ensemble.")
    price_type, price_amount = "quote", None
    if unit == "hour" and amount:
        price_type, price_amount = "hourly", int(amount)
    elif unit == "job" and amount:
        price_type, price_amount = "fixed", int(amount)
    return {"title": title[:200], "description": " ".join(lines), "price_type": price_type, "price": price_amount,
            "category": (ob.prestations[0] if len(ob.prestations) == 1 else ob.trade_id)}


def bio_draft(ob: ProOnboarding, first_name: str = "") -> str:
    v = profile_values(ob)
    trade = ob.trade.name.lower() if ob.trade_id else "services"
    parts = [f"{trade.capitalize()} à {_place(ob)}." if ob.commune else f"{trade.capitalize()}."]
    if _experience_sentence(v["experience"]):
        parts.append(_experience_sentence(v["experience"]))
    if v["strengths"]:
        parts.append(f"Je sais faire : {_join(v['strengths'])}.")
    return " ".join(parts)


# ═══ Application aux modèles existants ════════════════════════════════════════════════════════════════════════════════

@transaction.atomic
def apply(user) -> Dict:
    """Crée/complète le profil professionnel du compte et l'offre proposée. Idempotent ; n'écrase jamais ce que l'utilisateur a saisi
    ailleurs ; l'offre n'est publique qu'une fois l'éligibilité acquise (règle inchangée)."""
    ob = ProOnboarding.objects.select_for_update().get(pk=onboarding_for(user).pk)
    done = _complete(ob)
    if not (done["trade"] and done["zone"] and done["questions"]):
        raise OnboardingError("incomplete", "Répondez d’abord aux questions du parcours.", 409)
    if user.user_type == "admin":
        raise OnboardingError("forbidden", "Un compte administrateur ne peut pas proposer de services.", 403)
    profile, _ = HandymanProfile.objects.get_or_create(user=user)
    v = profile_values(ob)
    fields = []
    if not experience_declared(profile) and v["experience"] is not None:   # la déclaration exacte, jamais une valeur arrondie
        profile.experience_years, profile.experience_label = v["experience"]["years"], v["experience"]["label"]
        fields += ["experience_years", "experience_label"]
    if not (profile.commune or "").strip():
        profile.commune, fields = ob.commune, fields + ["commune"]
    if not (profile.quartier or "").strip() and ob.quartier:
        profile.quartier, fields = ob.quartier, fields + ["quartier"]
    if not profile.availability and (v["days"] or v["slots"]):
        slots = v["slots"] or list(SLOT_LABELS)
        profile.availability, fields = {d: slots for d in (v["days"] or list(DAY_LABELS))}, fields + ["availability"]
    bio = bio_draft(ob, user.first_name or "")
    if not (profile.bio or "").strip() or (profile.bio or "").strip() == ob.generated_bio.strip():
        profile.bio, fields = bio, fields + ["bio"]
        ob.generated_bio = bio
    price = v["price"] or {}
    rate_field = {"hour": "hourly_rate", "day": "daily_rate", "month": "monthly_rate"}.get(price.get("unit"))
    if rate_field and price.get("amount") and not getattr(profile, rate_field):
        setattr(profile, rate_field, int(price["amount"]))
        fields.append(rate_field)
    if fields:
        profile.save(update_fields=list(dict.fromkeys(fields)))
    profile.skills.add(*([ob.trade_id] + list(ob.prestations)))
    draft = offer_draft(ob)
    service = ob.service if ob.service_id and ob.service.handyman_id == user.pk else None
    if service is None:
        service = Service.objects.create(handyman=user, category_id=draft["category"], title=draft["title"], description=draft["description"],
                                         price_type=draft["price_type"], price=draft["price"], is_active=True)
    elif service.description.strip() == ob.generated_description.strip():          # jamais retouchée : mise à jour avec les réponses
        service.title, service.description = draft["title"], draft["description"]
        service.price_type, service.price, service.category_id = draft["price_type"], draft["price"], draft["category"]
        service.save(update_fields=["title", "description", "price_type", "price", "category"])
    ob.service, ob.generated_description, ob.applied_at = service, draft["description"], timezone.now()
    ob.save(update_fields=["service", "generated_bio", "generated_description", "applied_at", "updated_at"])
    return state(user)


# ═══ Progression : étapes faites, prochaine action, un seul bouton « Continuer » ═══════════════════════════════════════

def state(user) -> Dict:
    from handy.eligibility import eligibility_summary, experience_minimum

    ob = onboarding_for(user)
    done = _complete(ob)
    profile = HandymanProfile.objects.filter(user=user).first()
    e = eligibility_summary(profile) if profile else None
    has_photo = bool(profile and profile.photo)
    kyc = (e or {}).get("kyc", {}).get("status", "draft")
    status = {
        "trade": done["trade"], "zone": done["zone"], "questions": done["questions"], "account": True,
        "phone": bool(user.is_verified), "offer": ob.applied_at is not None and ob.service_id is not None,
        "photo": has_photo, "identity": kyc == "approved",
        "approval": bool(e and e["publication"]["authorized"]),
    }
    # Expérience déclarée sous le minimum d'un métier exercé : la publication est bloquée par la règle, pas en attente de l'équipe.
    if profile is not None:
        minimum = experience_minimum(profile)
    else:                                                                    # avant le profil : le métier choisi (et ses prestations)
        cats = list(ServiceCategory.objects.filter(pk__in=[ob.trade_id, *ob.prestations], min_experience_years__gt=0)) if ob.trade_id else []
        top = max(cats, key=lambda c: c.min_experience_years, default=None)
        minimum = {"years": top.min_experience_years, "trade": top.name} if top else {"years": 0, "trade": ""}
    v = profile_values(ob) if ob.trade_id else {"experience": None}
    declared = ({"years": profile.experience_years, "label": profile.experience_label} if profile and experience_declared(profile)
                else v["experience"])
    experience_ok = declared is None or declared["years"] >= minimum["years"]
    waiting = {"identity": kyc == "pending", "approval": kyc == "approved" and not status["approval"] and experience_ok}
    steps = [{"key": k, "label": label, "state": "done" if status[k] else ("waiting" if waiting.get(k) else "todo")} for k, label in JOURNEY]
    actions = {
        "trade": ("resume", "Choisir mon métier"), "zone": ("resume", "Choisir mon quartier"),
        "questions": ("resume", "Répondre aux questions"), "phone": ("verify_phone", "Confirmer mon téléphone"),
        "offer": ("apply", "Créer mon annonce"), "photo": ("photo", "Ajouter ma photo"),
        "identity": ("verify_identity", "Vérifier mon identité"),
    }
    # Prochaine action = première étape que l'UTILISATEUR peut faire ; sinon on attend l'équipe (jamais un « Continuer » sans effet).
    nxt = next((s for s in steps if s["state"] == "todo" and s["key"] in actions), None)
    if nxt is not None:
        code, label = actions[nxt["key"]]
        next_action = {"code": code, "label": label, "step": nxt["key"]}
    elif not experience_ok:
        n = minimum["years"]
        next_action = {"code": "blocked", "step": "approval",
                       "label": f"{minimum['trade']} demande au moins {n} an{'s' if n > 1 else ''} d’expérience pour publier"}
    elif not status["approval"]:
        pending = next((s for s in steps if s["state"] != "done"), None)
        next_action = {"code": "wait", "label": "Nous vérifions votre dossier", "step": pending["key"] if pending else "approval"}
    else:
        next_action = {"code": "done", "label": "Voir mon annonce", "step": None}
    return {
        "path": ob.path,
        "trade": {"id": ob.trade_id, "name": ob.trade.name} if ob.trade_id else None,
        "prestations": ob.prestations, "commune": ob.commune, "quartier": ob.quartier, "answers": ob.answers, "step": ob.step,
        "offer": offer_draft(ob) if ob.trade_id else None,
        "service_id": ob.service_id,
        "steps": steps,
        "done": sum(1 for s in steps if s["state"] == "done"),
        "total": len(steps),
        "next_action": next_action,
        "published": status["approval"],
        "experience": {"declared": declared["label"] if declared else "", "years": declared["years"] if declared else None,
                       "minimum": minimum["years"], "trade": minimum["trade"], "ok": experience_ok},
    }
