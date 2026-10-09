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

from handy.eligibility import is_publishable, profile_checklist
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
    docs = HandymanDocument.objects.filter(handyman=profile)
    approved = set(docs.filter(status="approved").values_list("document_type", flat=True))
    required = sorted(HandymanProfile.REQUIRED_KYC_DOCS)
    if set(required).issubset(approved):
        state = "approved"
    elif docs.filter(status="pending").exists():
        state = "pending"
    elif docs.filter(status="rejected").exists():
        state = "rejected"
    else:
        state = "none"
    rejected = docs.filter(status="rejected").order_by("-reviewed_at", "-uploaded_at").first()
    return {
        "status": state,
        "required": required,
        "documents": {s: docs.filter(status=s).count() for s in ("pending", "approved", "rejected")},
        "rejection_reason": (rejected.rejection_reason or None) if rejected and state == "rejected" else None,
    }


def _provider_block(user, profile, now) -> dict:
    missions = Booking.objects.filter(handyman=user)
    checklist = profile_checklist(profile)
    done = sum(1 for i in checklist if i["done"])
    upcoming = (missions.filter(status__in=ACTIVE_STATUSES)
                .select_related("client", "service", "service__category")
                .order_by("booking_date", "id")[:LIST_SIZE])
    return {
        "profile_id": profile.id,
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

    received = Review.objects.filter(booking__handyman=user)
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
            "display_name": public_name(user) if user.first_name else (user.username or "Membre Tratra"),
            "phone": user.phone or None,
            "is_verified": bool(user.is_verified),
            "user_type": user.user_type,
        },
        "capabilities": {
            "client": user.user_type != "admin",
            "provider": profile is not None,
            "publishable": bool(provider and provider["publishable"]),
            "company": user.user_type == "entreprise" or CompanyProfile.objects.filter(user=user).exists(),
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
    publishable = is_publishable(HandymanProfile.objects.filter(user=user).first())
    services = (Service.objects.filter(handyman=user).select_related("category")
                .annotate(bookings_count=Count("bookings")).order_by("-created_at", "-id"))
    return Response({
        "publishable": publishable,
        "results": [{
            "id": s.id, "title": s.title, "category": s.category.name if s.category_id else None,
            "price": str(s.price) if s.price is not None else None, "price_type": s.price_type,
            "duration": s.duration, "is_active": s.is_active,
            "published": bool(s.is_active and publishable),  # visible dans le catalogue public
            "bookings_count": s.bookings_count,
        } for s in services],
    })


def _conversation_item(conv, user) -> dict:
    others = [p for p in conv.participants.all() if p.pk != user.pk]
    last = conv.messages.order_by("-created_at", "-id").first()
    unread = conv.messages.filter(is_read=False).exclude(sender=user).count()
    return {
        "id": conv.id,
        "booking_id": conv.booking_id,
        "counterpart": public_name(others[0]) if others else "Membre Tratra",
        "last_message": (last.content[:140] if last else None),
        "last_at": (last.created_at.isoformat() if last else conv.updated_at.isoformat()),
        "unread": unread,
    }


@never_cache  # données propres à l'utilisateur : jamais mises en cache (proxy, CDN, navigateur)
@extend_schema(request=OpenApiTypes.OBJECT, responses=OpenApiTypes.OBJECT, tags=["Compte"],
               summary="Mes conversations (GET) / ouvrir la conversation d'une réservation (POST)")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
def me_conversations(request):
    user = request.user
    if request.method == "POST":
        booking = Booking.objects.filter(pk=request.data.get("booking")).first()
        if booking is None or user.pk not in (booking.client_id, booking.handyman_id):
            return Response({"detail": "Réservation introuvable."}, status=status.HTTP_404_NOT_FOUND)
        if booking.handyman_id is None:
            return Response({"detail": "Aucun artisan n'est encore associé à cette réservation."},
                            status=status.HTTP_400_BAD_REQUEST)
        conv = Conversation.objects.filter(booking=booking, participants=booking.client).filter(
            participants=booking.handyman).first()
        created = conv is None
        if created:
            conv = Conversation.objects.create(booking=booking)
            conv.participants.set([booking.client, booking.handyman])
        return Response({"id": conv.id, "created": created},
                        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
    convs = (Conversation.objects.filter(participants=user).distinct()
             .prefetch_related("participants").order_by("-updated_at", "-id")[:50])
    return Response({"results": [_conversation_item(c, user) for c in convs]})


@never_cache  # données propres à l'utilisateur : jamais mises en cache (proxy, CDN, navigateur)
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Compte"],
               summary="Messages d'une de mes conversations (GET) / les marquer lus (POST)")
@api_view(["GET", "POST"])
@permission_classes([permissions.IsAuthenticated])
def me_conversation_messages(request, pk):
    user = request.user
    conv = Conversation.objects.filter(pk=pk, participants=user).first()
    if conv is None:
        return Response({"detail": "Conversation introuvable."}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "POST":  # marque lus les messages REÇUS (jamais ceux d'autrui à autrui)
        n = conv.messages.filter(is_read=False).exclude(sender=user).update(is_read=True)
        return Response({"marked": n})
    msgs = conv.messages.select_related("sender").order_by("-created_at", "-id")[:100]
    return Response({
        "conversation": _conversation_item(conv, user),
        "results": [{
            "id": m.id, "mine": m.sender_id == user.pk, "content": m.content,
            "created_at": m.created_at.isoformat(), "is_read": m.is_read,
        } for m in reversed(list(msgs))],
    })


@never_cache  # données propres à l'utilisateur : jamais mises en cache (proxy, CDN, navigateur)
@extend_schema(request=None, responses=OpenApiTypes.OBJECT, tags=["Compte"],
               summary="Mes avis : reçus, donnés et à rédiger")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me_reviews(request):
    user = request.user

    def row(r, other):
        service = r.booking.service
        return {"id": r.id, "rating": r.rating, "comment": r.comment or "", "created_at": r.created_at.isoformat(),
                "booking_id": r.booking_id, "service": service.title if service else None,
                "author" if other == "client" else "artisan": public_name(
                    r.booking.client if other == "client" else r.booking.handyman)}

    base = Review.objects.select_related("booking", "booking__service", "booking__client", "booking__handyman")
    received = [row(r, "client") for r in base.filter(booking__handyman=user).order_by("-created_at")[:50]]
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
    n = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({"marked": n})
