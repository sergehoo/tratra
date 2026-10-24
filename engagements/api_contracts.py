"""API du module Contrats : signature, documents scellés, modèles utilisables, invitations, vérification PUBLIQUE.

Confidentialité : le PDF n'est remis qu'aux parties (et au personnel habilité via le Back-Office) ; la vérification publique ne renvoie
ni nom, ni montant, ni adresse, ni téléphone. Les refus de vérification (jeton mal formé, inconnu) ont la même forme et le même code."""
import mimetypes

from django.http import FileResponse
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes, throttle_classes
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from engagements import documents, serializers as S, signing
from engagements.api import contract_or_404, endpoint, posting_or_404
from engagements.models import ContractDocument, ContractTemplate, EngagementInvitation
from engagements.services import contracts as contract_svc
from engagements.services import postings as posting_svc
from engagements.services.common import EngagementError, contracts_for
from handy.models import ServiceCategory
from handy.security import client_ip

MAX_VERIFY_BYTES = 15 * 1024 * 1024
UNKNOWN = {"state": "unknown", "label": "Aucun document Tratra ne correspond à ce QR code ou à ce lien."}


# ── Parties ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@endpoint(["POST"], "Signer le contrat (signature électronique simple)", idempotent="contract.sign")
def contract_sign(request, pk):
    c = contract_or_404(request, pk)
    contract_svc.sign(c, request.user, consent=request.data.get("consent") is True, ip=client_ip(request),
                      user_agent=request.META.get("HTTP_USER_AGENT", ""))
    return Response(S.contract(contract_or_404(request, pk), request.user, detail=True))


@endpoint(["GET"], "Documents scellés d'un contrat (parties)")
def contract_documents(request, pk):
    c = contract_or_404(request, pk)
    return Response({"results": [S.document(d) for d in c.documents.order_by("issued_at")],
                     "verification": "Chaque document porte un QR code de vérification publique ; son empreinte SHA-256 et le scellement "
                                     "Ed25519 de Tratra prouvent qu'il n'a pas été modifié."})


@endpoint(["GET"], "PDF d'un document scellé (parties uniquement)")
def document_pdf(request, pk):
    doc = ContractDocument.objects.select_related("contract").filter(pk=pk, contract__in=contracts_for(request.user)).first()
    if doc is None:
        raise EngagementError("not_found", "Document introuvable.", 404)
    if not documents.stored_file_intact(doc):        # stockage altéré : jamais remis tel quel
        import logging

        logging.getLogger(__name__).critical("Document de contrat %s : fichier conservé différent de son empreinte.", doc.reference)
        raise EngagementError("document_altered", "Ce document est momentanément indisponible : l'équipe Tratra a été alertée.", 409)
    response = FileResponse(doc.file.open("rb"), content_type="application/pdf", as_attachment=True, filename=f"{doc.reference}-v{doc.version}.pdf")
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@endpoint(["GET"], "Modèles de contrat validés utilisables (nature, métier)")
def templates_usable(request):
    from engagements.services import templates as tpl

    relationship = request.query_params.get("relationship", "independent")
    category = ServiceCategory.objects.filter(pk=request.query_params.get("category") or 0).first()
    best = tpl.template_for(relationship, category)
    qs = ContractTemplate.objects.filter(status=ContractTemplate.VALIDATED, relationship=relationship).prefetch_related("categories")
    return Response({"default": best.pk if best else None, "results": [S.template(t) for t in qs],
                     "notice": "Sans modèle validé juridiquement, le contrat reste une acceptation électronique simple des conditions, "
                               "sans document scellé." if best is None else ""})


# ── Invitations ─────────────────────────────────────────────────────────────────────────────────────────────────────

@endpoint(["GET", "POST"], "Invitations d'un besoin (auteur) / inviter un professionnel vérifié", idempotent="invitation.create", verified=True)
def posting_invitations(request, pk):
    p = posting_or_404(request, pk, owner_only=True)
    if request.method == "POST":
        i = posting_svc.invite(p, request.user, request.data.get("invitee"), request.data.get("message", ""))
        return Response(S.invitation(i, request.user), status=201)
    qs = p.invitations.select_related("posting", "posting__category", "invitee", "invited_by")
    return Response({"results": [S.invitation(i, request.user) for i in qs]})


@endpoint(["GET"], "Mes invitations à candidater")
def invitations_mine(request):
    qs = EngagementInvitation.objects.filter(invitee=request.user).select_related("posting", "posting__category", "invitee", "invited_by")
    return Response({"results": [S.invitation(i, request.user) for i in qs[:100]]})


def _invitation_or_404(request, pk):
    i = EngagementInvitation.objects.select_related("posting", "posting__category", "invitee", "invited_by").filter(pk=pk).first()
    if i is None or (i.invitee_id != request.user.id and not posting_svc.posting_side(i.posting, request.user)):
        raise EngagementError("not_found", "Invitation introuvable.", 404)
    return i


@endpoint(["POST"], "Accepter (candidater) ou décliner une invitation", verified=True)
def invitation_respond(request, pk):
    i = _invitation_or_404(request, pk)
    accept = request.data.get("accept")
    if not isinstance(accept, bool):
        raise EngagementError("invalid", "`accept` doit être vrai ou faux.", 400, fields={"accept": "Booléen attendu."})
    i = posting_svc.respond_invitation(i, request.user, accept, request.data)
    return Response(S.invitation(_invitation_or_404(request, i.pk), request.user))


@endpoint(["POST"], "Retirer une invitation (auteur du besoin)")
def invitation_cancel(request, pk):
    i = posting_svc.cancel_invitation(_invitation_or_404(request, pk), request.user)
    return Response(S.invitation(_invitation_or_404(request, i.pk), request.user))


# ── Vérification publique (aucune authentification, aucune donnée personnelle) ─────────────────────────────────────

@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def verify_token(request, token):
    doc = documents.by_token(token)
    response = Response(documents.public_result(doc) if doc else UNKNOWN, status=200 if doc else 404)
    response["Cache-Control"] = "no-store"
    return response


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
@parser_classes([MultiPartParser])
def verify_file(request):
    upload = request.FILES.get("file")
    if upload is None or upload.size > MAX_VERIFY_BYTES:
        return Response({"match": False, "state": "unknown", "label": "Déposez le PDF du contrat (15 Mo au plus)."}, status=400)
    data = upload.read(MAX_VERIFY_BYTES + 1)
    if not data.startswith(b"%PDF-"):
        return Response({"match": False, "state": "unknown", "label": "Ce fichier n'est pas un PDF."}, status=400)
    doc = documents.by_file(data)      # le fichier n'est ni conservé ni journalisé : seule son empreinte est comparée
    if doc is None:
        return Response({"match": False, **UNKNOWN, "label": "Aucun document Tratra ne correspond exactement à ce fichier : il a pu être modifié."})
    return Response({"match": True, **documents.public_result(doc)})


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def public_keys(request):
    return Response({"algorithm": signing.ALGORITHM, "payload": "JSON canonique (clés triées, sans espace, UTF-8) des champs reference, kind, "
                     "stage, version, sha256, terms_hash, issued_at", "keys": signing.public_keys()})


for _view in (verify_token, verify_file, public_keys):
    _view.cls.throttle_scope = "verify"          # 60 vérifications par minute et par adresse
