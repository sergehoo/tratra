"""Back-Office « Contrats » : modèles juridiques (rédaction, revue, VALIDATION HUMAINE), documents scellés (révocation), clés de
scellement (rotation, révocation). Chaque action est réservée à un droit dédié et journalisée ; la clé privée ne sort jamais.

Droits : lecture `engagements.view` ; modèles `contracts.templates` ; validation `contracts.legal_review` (rôle « legal ») ;
révocation d'un document `contracts.revoke` ; clés `contracts.keys` (Super Admin)."""
from rest_framework.response import Response

from backoffice.common import BOView, audit_op, bad_request
from engagements import documents, serializers as S, signing
from engagements.models import ContractDocument, ContractTemplate, EngagementContract, SigningKey
from engagements.services import templates as tpl
from engagements.services.common import EngagementError


def _error(exc: EngagementError) -> Response:
    return Response({"code": exc.code, "detail": exc.message, **exc.extra}, status=exc.status)


def _template_or_404(pk):
    return ContractTemplate.objects.prefetch_related("categories").select_related("reviewed_by").filter(pk=pk).first()


class TemplateList(BOView):
    bo_permission = {"GET": "engagements.view", "POST": "contracts.templates"}

    def get(self, request):
        qs = ContractTemplate.objects.prefetch_related("categories").select_related("reviewed_by")
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        return Response({"results": [S.template(t) for t in qs],
                         "statuses": [{"id": k, "label": v} for k, v in ContractTemplate.STATUSES],
                         "notice": "Un modèle n'est utilisable qu'une fois validé par revue juridique humaine. Aucun modèle n'est déclaré "
                                   "« conforme » par Tratra."})

    def post(self, request):
        try:
            t = tpl.create(request.user, request.data)
        except EngagementError as exc:
            return _error(exc)
        audit_op(request, "contract_template.created", t, code=t.code, version=t.version)
        return Response(S.template(_template_or_404(t.pk), detail=True), status=201)


class TemplateDetail(BOView):
    bo_permission = {"GET": "engagements.view", "PATCH": "contracts.templates"}

    def get(self, request, pk):
        t = _template_or_404(pk)
        return Response(S.template(t, detail=True)) if t else bad_request("not_found", "Modèle introuvable.", 404)

    def patch(self, request, pk):
        t = _template_or_404(pk)
        if t is None:
            return bad_request("not_found", "Modèle introuvable.", 404)
        try:
            t = tpl.update(t, request.user, request.data)
        except EngagementError as exc:
            return _error(exc)
        audit_op(request, "contract_template.updated", t, code=t.code, version=t.version)
        return Response(S.template(_template_or_404(t.pk), detail=True))


class TemplateAction(BOView):
    """submit (brouillon → à valider), validate (revue juridique faite : droit dédié), retire, new_version."""
    bo_permission = "contracts.templates"
    ACTIONS = {"submit", "validate", "retire", "new_version"}

    def post(self, request, pk, action):
        from backoffice import rbac

        t = _template_or_404(pk)
        if t is None or action not in self.ACTIONS:
            return bad_request("not_found", "Introuvable.", 404)
        if action == "validate" and not rbac.has_permission(request.user, "contracts.legal_review"):
            return bad_request("forbidden", "Seule une personne habilitée à la revue juridique peut valider un modèle.", 403)
        try:
            if action == "submit":
                t = tpl.submit(t, request.user)
            elif action == "validate":
                t = tpl.validate(t, request.user, reviewed_by_name=str(request.data.get("reviewed_by_name") or ""),
                                 note=str(request.data.get("note") or ""))
            elif action == "retire":
                t = tpl.retire(t, request.user)
            else:
                t = tpl.new_version(t, request.user)
        except EngagementError as exc:
            return _error(exc)
        audit_op(request, f"contract_template.{action}", t, code=t.code, version=t.version)
        return Response(S.template(_template_or_404(t.pk), detail=True), status=201 if action == "new_version" else 200)


class ContractDocuments(BOView):
    bo_permission = "engagements.view"

    def get(self, request, pk):
        c = EngagementContract.objects.filter(pk=pk).first()
        if c is None:
            return bad_request("not_found", "Contrat introuvable.", 404)
        rows = []
        for d in c.documents.select_related("signing_key").order_by("issued_at"):
            rows.append({**S.document(d), "public": documents.public_result(d)["state"],
                         "signatures": [{"role": s.role, "signed_at": s.signed_at} for s in d.signatures.all()]})
        return Response({"reference": c.reference, "results": rows})


class DocumentRevoke(BOView):
    bo_permission = "contracts.revoke"

    def post(self, request, pk):
        d = ContractDocument.objects.select_related("contract").filter(pk=pk).first()
        if d is None:
            return bad_request("not_found", "Document introuvable.", 404)
        reason = str(request.data.get("reason") or "").strip()
        if len(reason) < 10:
            return bad_request("reason_required", "Motif d'au moins 10 caractères obligatoire.", 400)
        d = documents.revoke(d, actor=request.user, reason=reason)
        audit_op(request, "contract_document.revoked", d.contract, reference=d.reference, reason=reason[:300])
        return Response(S.document(d))


class SigningKeys(BOView):
    bo_permission = "contracts.keys"

    def get(self, request):
        return Response({"results": signing.public_keys(), "notice": "Les clés privées sont chiffrées côté serveur et ne sont jamais affichées."})

    def post(self, request):
        """{"action": "rotate"} ou {"action": "revoke", "kid": "...", "reason": "..."}."""
        action = request.data.get("action")
        if action == "rotate":
            key = signing.generate_key(actor=request.user)
            audit_op(request, "contract_key.rotated", None, kid=key.kid)
            return Response({"kid": key.kid, "status": key.status}, status=201)
        if action == "revoke":
            reason = str(request.data.get("reason") or "").strip()
            if len(reason) < 10:
                return bad_request("reason_required", "Motif d'au moins 10 caractères obligatoire.", 400)
            try:
                key = signing.revoke_key(str(request.data.get("kid") or ""), actor=request.user, reason=reason)
            except signing.SigningError as exc:
                return bad_request("not_found", str(exc), 404)
            audit_op(request, "contract_key.revoked", None, kid=key.kid, reason=reason[:300])
            active = SigningKey.objects.filter(status=SigningKey.ACTIVE).values_list("kid", flat=True).first()
            return Response({"kid": key.kid, "status": key.status, "active": active})
        return bad_request("invalid", "Action inconnue (rotate, revoke).", 400)
