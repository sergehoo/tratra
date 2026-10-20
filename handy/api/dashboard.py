"""Tableau de bord utilisateur UNIFIÉ (un compte = client ET/OU artisan).

`GET  /me/dashboard/`        agrégation en lecture seule des données réelles de l'utilisateur
                             courant (aucun KPI inventé : tout vient de la base).
`POST /me/handyman-profile/` crée le profil professionnel LIÉ AU COMPTE EXISTANT (jamais un
                             second compte) ; idempotent. Ne touche ni au KYC, ni à la
                             validation, ni à la publication : celles-ci restent régies par
                             `handy/eligibility.py`.

Les « destinations » renvoyées (`target`) sont des clés neutres que chaque client (web, Flutter)
traduit en écran : le backend ne connaît aucune URL d'interface.
"""

from django.views.decorators.cache import never_cache
from django.db.models import Avg, Count, Q
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from handy.api.serializers import absolute_media_url
from handy.eligibility import eligibility_summary, is_publishable, profile_checklist
from handy import addresses as address_service
from handy.models import (
    Booking, CompanyProfile, Conversation, HandymanDocument, HandymanProfile, Message, Notification, Review, Service,
    artisan_available_earnings,
)

BOOKING_STATUSES = ("pending", "confirmed", "in_progress", "completed", "cancelled")
ACTIVE_STATUSES = ("pending", "confirmed", "in_progress")
LIST_SIZE = 5


def public_name(user) -> str:
    """« Prénom N. » — jamais le nom complet, l'e-mail ni l'identifiant d'un tiers."""
    if user is None:
        return "Membre Tratra"
    first = (user.first_name or "").strip()
    last = (user.last_name or "").strip()
    if not first:
        return "Membre Tratra"
    return f"{first} {last[0]}." if last else first


def _counts(qs) -> dict:
    rows = dict(qs.values_list("status").annotate(n=Count("id")).values_list("status", "n"))
    counts = {s: int(rows.get(s, 0)) for s in BOOKING_STATUSES}
    counts["total"] = sum(counts.values())
    return counts


def _item(booking, role: str) -> dict:
    other = booking.handyman if role == "client" else booking.client
    service = booking.service
    return {
        "id": booking.id,
        "role": role,  # « client » : j'ai réservé ; « handyman » : on m'a réservé
        "title": service.title if service else f"Réservation #{booking.id}",
        "category": service.category.name if service and service.category_id else None,
        "status": booking.status,
        "booking_date": booking.booking_date.isoformat() if booking.booking_date else None,
        "city": booking.city or None,
        "counterpart": public_name(other),
    }


def _kyc(profile) -> dict:
    """État d'IDENTITÉ (pièce d'identité seulement, comme le parcours guidé et l'éligibilité) : un justificatif professionnel en attente
    ne fait plus afficher « vérification en cours » à un artisan dont l'identité est déjà vérifiée."""
    from handy.kyc_flow import kyc_status

    docs = HandymanDocument.objects.filter(handyman=profile)
    identity = kyc_status(profile)
    state = {"draft": "none"}.get(identity["status"], identity["status"])
    return {
        "status": state,
        "label": identity["label"],
        "required": sorted(HandymanProfile.REQUIRED_KYC_DOCS),
        "documents": {s: docs.filter(status=s).count() for s in ("pending", "approved", "rejected")},
        "rejection_reason": identity["reason"] if state == "rejected" else None,
    }


def _provider_block(user, profile, now) -> dict:
    missions = Booking.objects.filter(handyman=user)
    checklist = profile_checklist(profile)
    done = sum(1 for i in checklist if i["done"])
    upcoming = (missions.filter(status__in=ACTIVE_STATUSES)
                .select_related("client", "service", "service__category")
                .order_by("booking_date", "id")[:LIST_SIZE])
    from trust.engine import evaluate_profile
    from trust.models import BadgeAward

    if profile.trust_evaluated_at is None:  # profil antérieur à Tratra Trust : première évaluation à la demande
        evaluate_profile(profile, trigger="dashboard")
    return {
        "profile_id": profile.id,
        # Badges Tratra Trust ACTUELS (NOUVEAU tant que l'identité n'est pas vérifiée) et score s'il est calculable.
        "badges": [{"code": c, "label": BadgeAward.LABELS[c]} for c in (profile.trust_badges or []) if c in BadgeAward.LABELS],
        "trust_score": profile.trust_score,
        "online": bool(profile.online),
        "is_approved": bool(profile.is_approved),
        "publishable": is_publishable(profile),
        "rating": float(profile.rating) if profile.rating else None,
        "completed_jobs": int(profile.completed_jobs or 0),
        "completion": {
            "percent": round(100 * done / len(checklist)) if checklist else 0,
            "done": done,
            "total": len(checklist),
            "items": checklist,
        },
        "kyc": _kyc(profile),
        # Profil complet / identité / autorisation de publication / offres : quatre notions distinctes, blocages et actions (source unique).
        "eligibility": eligibility_summary(profile),
        "services": {
            "active": Service.objects.filter(handyman=user, is_active=True).count(),
            "total": Service.objects.filter(handyman=user).count(),
        },
        "missions": _counts(missions),
        "earnings": {"available": str(artisan_available_earnings(user)), "currency": "XOF"},
        "next_missions": [_item(b, "handyman") for b in upcoming],
    }


def _actions(user, provider, client_block, unread) -> list:
    """Éléments qui demandent une action de l'utilisateur, du plus urgent au moins urgent."""
    actions = []
    if provider:
        pending = provider["missions"]["pending"]
        if pending:
            actions.append({
                "key": "missions_pending", "severity": "warning", "target": "provider",
                "title": f"{pending} demande{'s' if pending > 1 else ''} de mission à traiter",
                "description": "Acceptez ou refusez pour ne pas laisser le client en attente.",
            })
        kyc = provider["kyc"]
        if kyc["status"] == "rejected":
            actions.append({
                "key": "kyc_rejected", "severity": "danger", "target": "profile_kyc",
                "title": "Un document d'identité a été refusé",
                "description": kyc["rejection_reason"] or "Déposez-le à nouveau pour poursuivre la vérification.",
            })
        elif kyc["status"] == "none":
            actions.append({
                "key": "kyc_missing", "severity": "info", "target": "profile_kyc",
                "title": "Déposez votre pièce d'identité",
                "description": "Étape nécessaire pour publier vos services et recevoir des missions.",
            })
        completion = provider["completion"]
        missing_profile = [i for i in completion["items"] if not i["done"] and i["key"] not in ("kyc", "approval")]
        if missing_profile:
            actions.append({
                "key": "profile_incomplete", "severity": "info", "target": "profile",
                "title": f"Complétez votre profil professionnel ({completion['done']}/{completion['total']})",
                "description": "Encore : " + ", ".join(i["label"].lower() for i in missing_profile) + ".",
            })
    to_write = client_block["reviews_to_write"]
    if to_write:
        actions.append({
            "key": "reviews_to_write", "severity": "info", "target": "reviews",
            "title": f"Donnez votre avis sur {to_write} prestation{'s' if to_write > 1 else ''}",
            "description": "Votre retour aide les autres clients et l'artisan.",
        })
    if user.phone and not user.is_verified:
        actions.append({
            "key": "phone_unverified", "severity": "warning", "target": "verify_phone",
            "title": "Vérifiez votre numéro de téléphone",
            "description": "Un code vous est envoyé par SMS pour sécuriser votre compte.",
        })
    if unread["messages"]:
        actions.append({
            "key": "messages_unread", "severity": "info", "target": "messages",
            "title": f"{unread['messages']} message{'s' if unread['messages'] > 1 else ''} non lu{'s' if unread['messages'] > 1 else ''}",
            "description": "Répondez pour confirmer les détails de l'intervention.",
        })
    order = {"danger": 0, "warning": 1, "info": 2}
    return sorted(actions, key=lambda a: order[a["severity"]])


@never_cache  # données propres à l'utilisateur : jamais mises en cache (proxy, CDN, navigateur)
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Compte"],
               summary="Tableau de bord unifié de l'utilisateur connecté")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me_dashboard(request):
    user = request.user
    now = timezone.now()
    profile = HandymanProfile.objects.filter(user=user).first()

    bookings = Booking.objects.filter(client=user)
    upcoming_client = (bookings.filter(status__in=ACTIVE_STATUSES)
                       .select_related("handyman", "service", "service__category")
                       .order_by("booking_date", "id")[:LIST_SIZE])
    recent_client = (bookings.select_related("handyman", "service", "service__category")
                     .order_by("-created_at", "-id")[:LIST_SIZE])
    client_block = {
        "bookings": _counts(bookings),
        "next_bookings": [_item(b, "client") for b in upcoming_client],
        "recent_bookings": [_item(b, "client") for b in recent_client],
        "reviews_to_write": bookings.filter(status="completed", review__isnull=True).count(),
    }

    provider = _provider_block(user, profile, now) if profile else None
    if provider:
        recent_missions = (Booking.objects.filter(handyman=user)
                           .select_related("client", "service", "service__category")
                           .order_by("-created_at", "-id")[:LIST_SIZE])
        provider["recent_missions"] = [_item(b, "handyman") for b in recent_missions]

    received = Review.objects.filter(booking__handyman=user, revealed_at__isnull=False)
    reviews = received.aggregate(count=Count("id"), average=Avg("rating"))
    unread = {
        "notifications": Notification.objects.filter(user=user, is_read=False).count(),
        "messages": (Message.objects.filter(conversation__participants=user, is_read=False)
                     .exclude(sender=user).distinct().count()),
    }

    # Prochaines interventions : toutes les dates à venir (réservations ET missions), triées.
    merged = [*client_block["next_bookings"], *(provider["next_missions"] if provider else [])]
    merged.sort(key=lambda i: (i["booking_date"] is None, i["booking_date"] or "", i["id"]))

    return Response({
        "generated_at": now.isoformat(),
        "user": {
            "id": user.id,
            "first_name": user.first_name or "",
            "display_name": public_name(user) if user.first_name else "Membre Tratra",  # jamais l'identifiant technique
            "phone": user.phone or None,
            "is_verified": bool(user.is_verified),
            "user_type": user.user_type,
            "address_complete": address_service.is_complete(user),  # demandée avant la première demande ou prestation, jamais à l'inscription
        },
        "capabilities": {
            "client": user.user_type != "admin",
            "provider": profile is not None,
            "publishable": bool(provider and provider["publishable"]),
            "company": user.user_type == "entreprise" or CompanyProfile.objects.filter(user=user).exists(),
            # Tratra Business : le compte est membre actif d'au moins une organisation (rôle et capacités : /business/orgs/).
            "business": user.business_memberships.filter(is_active=True, organization__is_active=True).exists(),
        },
        "client": client_block,
        "provider": provider,
        "upcoming": merged[:LIST_SIZE],
        "reviews": {
            "received_count": int(reviews["count"] or 0),
            "received_average": round(float(reviews["average"]), 1) if reviews["average"] else None,
            "to_write": client_block["reviews_to_write"],
        },
        "unread": unread,
        "actions": _actions(user, provider, client_block, unread),
    })


@never_cache  # données propres à l'utilisateur : jamais mises en cache (proxy, CDN, navigateur)
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Compte"],
               summary="Créer le profil professionnel du compte courant (idempotent)")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def me_become_provider(request):
    if request.user.user_type == "admin":
        return Response({"detail": "Un compte administrateur ne peut pas proposer de services."},
                        status=status.HTTP_403_FORBIDDEN)
    profile, created = HandymanProfile.objects.get_or_create(user=request.user)
    return Response({"created": created, "profile_id": profile.id},
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


# ---------------------------------------------------------------------------------------------
# Agrégations de lecture pour les pages du tableau de bord (mêmes règles d'accès que l'existant :
# chaque requête est bornée à l'utilisateur courant — aucun accès aux données d'autrui).
# ---------------------------------------------------------------------------------------------

@never_cache  # données propres à l'utilisateur : jamais mises en cache (proxy, CDN, navigateur)
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Compte"],
               summary="Mes services (y compris non publiés) avec leur état de publication")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me_services(request):
    user = request.user
    profile = HandymanProfile.objects.filter(user=user).first()
    publishable = is_publishable(profile)
    services = (Service.objects.filter(handyman=user).select_related("category", "category__parent")
                .annotate(bookings_count=Count("bookings")).order_by("-created_at", "-id"))

    def publication(s) -> dict:
        if not s.is_active:
            return {"state": "inactive", "label": "Désactivée", "hint": "Invisible des clients. Activez-la pour la proposer."}
        if publishable:
            return {"state": "published", "label": "Publiée", "hint": "Visible des clients dans le catalogue et la recherche."}
        return {"state": "waiting", "label": "En attente d’autorisation",
                "hint": "Elle sera publiée automatiquement dès que votre publication sera autorisée."}

    return Response({
        "publishable": publishable,
        "eligibility": eligibility_summary(profile) if profile is not None else None,
        "results": [{
            "id": s.id, "title": s.title, "category": s.category.name if s.category_id else None,
            "category_id": s.category_id,
            "trade": (s.category.parent.name if s.category_id and s.category.parent_id else None),
            "description": s.description or "",
            "price": str(s.price) if s.price is not None else None, "price_type": s.price_type,
            "duration": s.duration, "is_active": s.is_active,
            "published": bool(s.is_active and publishable),  # visible dans le catalogue public
            "publication": publication(s),
            "bookings_count": s.bookings_count,
        } for s in services],
    })


@never_cache  # données propres à l'utilisateur : jamais mises en cache (proxy, CDN, navigateur)
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Compte"],
               summary="Mes avis : reçus, donnés et à rédiger")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me_reviews(request):
    user = request.user

    def row(r, other):
        from handy.reviews import can_edit, can_reply

        service = r.booking.service
        item = {"id": r.id, "rating": r.rating, "comment": r.comment or "", "created_at": r.created_at.isoformat(),
                "booking_id": r.booking_id, "service": service.title if service else None,
                "criteria": {k: getattr(r, k) for k in Review.CRITERIA if getattr(r, k) is not None},
                # URL ABSOLUE : relative, elle serait résolue contre l'origine du site web (404) hors stockage objet.
                "photos": [u for u in (absolute_media_url(request, m.image) for m in r.media.all()) if u],
                "reply": ({"text": r.reply_text, "at": r.reply_at.isoformat() if r.reply_at else None}
                          if (r.reply_text or "").strip() else None),
                "author" if other == "client" else "artisan": public_name(
                    r.booking.client if other == "client" else r.booking.handyman)}
        if other == "client":   # avis REÇU : l'artisan peut répondre
            item["can_reply"] = bool(r.booking.status == "completed" and can_reply(r))
        else:                   # avis DONNÉ : l'auteur peut le corriger pendant la fenêtre
            item["can_edit"] = can_edit(r)
        return item

    base = Review.objects.select_related("booking", "booking__service", "booking__client", "booking__handyman").prefetch_related("media")
    received = [row(r, "client") for r in base.filter(booking__handyman=user, revealed_at__isnull=False).order_by("-created_at")[:50]]
    given = [row(r, "handyman") for r in base.filter(booking__client=user).order_by("-created_at")[:50]]
    to_write = (Booking.objects.filter(client=user, status="completed", review__isnull=True)
                .select_related("service", "handyman").order_by("-booking_date", "-id")[:20])
    return Response({
        "received": received,
        "given": given,
        "to_write": [{"booking_id": b.id, "service": b.service.title if b.service else f"Réservation #{b.id}",
                      "artisan": public_name(b.handyman),
                      "booking_date": b.booking_date.isoformat() if b.booking_date else None} for b in to_write],
    })


@never_cache  # données propres à l'utilisateur : jamais mises en cache (proxy, CDN, navigateur)
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Compte"],
               summary="Marquer toutes mes notifications comme lues")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def me_notifications_read_all(request):
    from handy import notifications
    n = notifications.mark_read(request.user)
    return Response({"marked": n})
