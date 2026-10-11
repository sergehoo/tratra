"""Briques communes du Back-Office : vue de base protégée par droit, pagination, audit, export CSV sûr, masquage.

Règles transverses (appliquées par chaque module) :
 - droit déclaré par la vue (`bo_permission`) ; une vue sans droit est refusée (HasBackOfficePermission) ;
 - toute opération sensible (changement d'état, accès à une pièce KYC, export, réglage) est journalisée (trust.AuditEvent) ;
 - jamais de secret, de jeton d'appareil (FCM) ni de pièce d'identité dans une réponse JSON ;
 - les exports neutralisent l'injection de formules (=, +, -, @) et sont journalisés."""
import csv
import io
import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Callable, Iterable, Optional

from django.core.cache import cache
from django.http import HttpResponse
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from backoffice import rbac
from backoffice.permissions import HasBackOfficePermission
from handy.api.views import DefaultPageNumberPagination
from trust.models import audit


class BOView(APIView):
    """Vue de base : `bo_permission = "module.action"` obligatoire (dict {méthode: code} accepté)."""
    permission_classes = [HasBackOfficePermission]
    bo_permission = None


def paginate(request, queryset, to_dict: Callable, *, page_size: int = 25):
    """Réponse paginée au format DRF `{count, next, previous, results}` ; `to_dict(obj)` sérialise une ligne."""
    paginator = DefaultPageNumberPagination()
    paginator.page_size = page_size
    page = paginator.paginate_queryset(queryset, request)
    response = paginator.get_paginated_response([to_dict(o) for o in page])
    if getattr(request, "_bo_contacts_unmasked", False):
        _audit_unmasked_contacts(request)
    return response


def audit_op(request, action: str, target=None, **data):
    """Journalise une opération sensible du Back-Office avec l'auteur (jamais de donnée secrète dans `data`)."""
    return audit(f"backoffice.{action}", actor=request.user, target=target, **data)


# ---- Dates ---------------------------------------------------------------------------------------------------------

def day_bounds(raw: Optional[str], *, end: bool = False):
    """« AAAA-MM-JJ » → début (ou fin) de journée aware ; valeur invalide ou vide → None (jamais d'erreur 500)."""
    if not raw:
        return None
    try:
        d = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None
    moment = datetime.combine(d, time.max if end else time.min)
    return timezone.make_aware(moment)


def apply_range(request, qs, field: str):
    """Filtre `from` / `to` (jours inclus) sur `field`."""
    start, stop = day_bounds(request.query_params.get("from")), day_bounds(request.query_params.get("to"), end=True)
    if start:
        qs = qs.filter(**{f"{field}__gte": start})
    if stop:
        qs = qs.filter(**{f"{field}__lte": stop})
    return qs


def last_days(n: int):
    """Début de journée d'il y a n-1 jours (fenêtre de n jours incluant aujourd'hui)."""
    today = timezone.localtime().date()
    return timezone.make_aware(datetime.combine(today - timedelta(days=n - 1), time.min))


def ordering(request, allowed: dict, default: str):
    """`?ordering=-created_at` restreint à une liste blanche (clé publique → champ)."""
    raw = request.query_params.get("ordering") or default
    desc = raw.startswith("-")
    field = allowed.get(raw.lstrip("-"))
    if field is None:
        raw = default
        desc = raw.startswith("-")
        field = allowed[raw.lstrip("-")]
    return f"-{field}" if desc else field


# ---- Données personnelles ------------------------------------------------------------------------------------------

def is_super_admin(request) -> bool:
    """Vrai pour le rôle Super Admin (superutilisateur actif et membre du personnel) : seul rôle qui voit les coordonnées complètes
    dans les LISTES. Les autres rôles gardent les coordonnées masquées ; la fiche d'un compte reste réservée aux rôles autorisés."""
    return "super_admin" in rbac.user_roles(getattr(request, "user", None))


def _audit_unmasked_contacts(request) -> None:
    """Une trace par administrateur, module et tranche de 5 minutes : consulter des coordonnées complètes est un accès sensible, sans noyer
    le journal d'une ligne par page affichée."""
    module = getattr(getattr(request, "resolver_match", None), "url_name", "") or "liste"
    if cache.add(f"bo:unmasked:{request.user.pk}:{module}", 1, 300):
        audit_op(request, "contacts.unmasked_view", target_type="contacts", target_id=None, view=module)


def phone_for(request, phone: Optional[str]) -> Optional[str]:
    """Numéro masqué pour tous les rôles, complet pour le Super Admin (consultation journalisée)."""
    if is_super_admin(request) and phone:
        request._bo_contacts_unmasked = True
        return phone
    return mask_phone(phone)


def email_for(request, email: Optional[str]) -> Optional[str]:
    if is_super_admin(request) and email:
        request._bo_contacts_unmasked = True
        return email
    return mask_email(email)


def mask_phone(phone: Optional[str]) -> Optional[str]:
    """« +2250701234567 » → « +22507••••4567 » : identifie sans exposer le numéro complet dans les listes."""
    if not phone:
        return None
    digits = re.sub(r"\s+", "", phone)
    return f"{digits[:6]}••••{digits[-4:]}" if len(digits) > 10 else f"{digits[:2]}••••{digits[-2:]}"


def mask_email(email: Optional[str]) -> Optional[str]:
    if not email or "@" not in email:
        return None
    name, _, domain = email.partition("@")
    return f"{name[:1]}•••@{domain}"


def public_name(user) -> str:
    """« Prénom N. » (même règle que l'espace utilisateur) ; repli sur l'identifiant de compte."""
    first, last = (user.first_name or "").strip(), (user.last_name or "").strip()
    if not first:
        return f"Compte #{user.pk}"
    return f"{first} {last[0]}." if last else first


# ---- Export CSV ----------------------------------------------------------------------------------------------------

def _safe_cell(value) -> str:
    text = "" if value is None else str(value)
    # Injection de formule (tableur) : une cellule qui commence par = + - @ (ou tabulation / retour) est neutralisée.
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def csv_response(filename: str, header: Iterable[str], rows: Iterable[Iterable]) -> HttpResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow([_safe_cell(h) for h in header])
    for row in rows:
        writer.writerow([_safe_cell(c) for c in row])
    response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")   # BOM : accents sous Excel
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "private, no-store"
    return response


def money(value) -> str:
    """Montant en texte à 2 décimales, quel que soit l'état en mémoire (absent → « 0.00 »)."""
    return str((Decimal(value) if value is not None else Decimal("0")).quantize(Decimal("0.01")))


def bad_request(code: str, detail: str, status: int = 400) -> Response:
    return Response({"code": code, "detail": detail}, status=status)
