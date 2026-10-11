"""API membre des évaluations mutuelles (Web / Flutter). Chaque appel est borné au compte courant."""
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from django.conf import settings

from handy.api.dashboard import public_name
from handy.models import Booking, Review, User
from reputation import services
from reputation.models import ClientReview


def _error(exc: services.EvaluationError):
    body = {"code": exc.code, "detail": exc.detail}
    if exc.fields:
        body["fields"] = exc.fields
    return Response(body, status=exc.status)


@extend_schema(tags=["Évaluations"], summary="Mes évaluations à laisser, données et reçues, et ma réputation")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def me_evaluations(request):
    user = request.user
    given = [services.serialize(r, "client", user) | {"about": public_name(r.booking.handyman)} for r in Review.objects.filter(booking__client=user).select_related("booking__handyman").order_by("-created_at")[:50]]
    given += [services.serialize(r, "provider", user) | {"about": public_name(r.subject)} for r in ClientReview.objects.filter(author=user).select_related("subject").order_by("-created_at")[:50]]
    received = [{"id": r.pk, "rating": r.rating, "comment": r.comment, "from": public_name(r.author), "created_at": r.created_at,
                 "criteria": {k: getattr(r, k) for k in ClientReview.CRITERIA if getattr(r, k) is not None}, "can_contest": not r.contests.filter(author=user).exists()}
                for r in services.visible_client_reviews(user).select_related("author")[:50]]
    return Response({
        "pending": services.pending_for(user), "given": sorted(given, key=lambda x: x["created_at"], reverse=True), "received_as_requester": received,
        "provider_score": services.provider_score(user), "requester_score": services.requester_score(user),
        "missions_evaluated": services.missions_evaluated(user), "history": services.history(user),
        "rules": {"window_days": settings.EVALUATION_WINDOW_DAYS, "reveal_days": settings.EVALUATION_REVEAL_DAYS, "min_public_count": services.MIN_PUBLIC_COUNT},
    })


@extend_schema(tags=["Évaluations"], summary="Évaluer l'autre partie d'une mission terminée")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def booking_evaluation(request, pk):
    booking = Booking.objects.filter(pk=pk).first()
    if booking is None or services.role_of(booking, request.user) is None:
        return Response({"detail": "Introuvable."}, status=status.HTTP_404_NOT_FOUND)
    try:
        obj = services.create(booking, request.user, request.data)
    except services.EvaluationError as exc:
        return _error(exc)
    role = services.role_of(booking, request.user)
    return Response(services.serialize(obj, role, request.user), status=status.HTTP_201_CREATED)


@extend_schema(tags=["Évaluations"], summary="Contester une évaluation reçue")
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def client_review_contest(request, pk):
    review = ClientReview.objects.filter(pk=pk).first()
    if review is None:
        return Response({"detail": "Introuvable."}, status=status.HTTP_404_NOT_FOUND)
    try:
        c = services.contest(review, request.user, str(request.data.get("reason", "")))
    except services.EvaluationError as exc:
        return _error(exc)
    return Response({"id": c.pk, "status": c.status}, status=status.HTTP_201_CREATED)


@extend_schema(tags=["Évaluations"], summary="Score demandeur d'un client d'une de mes missions (agrégat uniquement)")
@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def requester_score(request, pk):
    if not Booking.objects.filter(client_id=pk, handyman=request.user).exists():
        return Response({"detail": "Introuvable."}, status=status.HTTP_404_NOT_FOUND)
    s = services.requester_score(User.objects.get(pk=pk))
    return Response({"count": s["count"], "average": s["average"], "public": s["public"]})
