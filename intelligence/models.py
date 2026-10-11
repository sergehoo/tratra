"""Contrôle intelligent : l'IA et les règles PROPOSENT, un administrateur DÉCIDE.

Aucune sanction, validation KYC, badge ou accusation de fraude n'est jamais déclenché ici. Un OCR n'est pas une preuve d'authenticité.
Le texte intégral d'un document n'est jamais conservé : seuls des champs structurés, une empreinte protégée du numéro et le hachage du fichier."""
from django.conf import settings
from django.db import models
from django.db.models import Q


class DocumentAnalysis(models.Model):
    RISK = [("low", "Faible"), ("medium", "Moyen"), ("high", "Élevé"), ("unknown", "Indéterminé")]

    document = models.ForeignKey("handy.HandymanDocument", on_delete=models.CASCADE, related_name="analyses")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    ocr_engine = models.CharField(max_length=20, blank=True, default="none")      # none | tesseract | anthropic
    external_used = models.BooleanField(default=False)                            # un fournisseur externe a-t-il reçu le document ?
    legal_basis = models.CharField(max_length=300, blank=True, default="")        # base légale déclarée au moment de l'envoi externe
    fields = models.JSONField(default=dict, blank=True)                           # champs structurés extraits (jamais le texte intégral)
    id_fingerprint = models.CharField(max_length=64, blank=True, default="", db_index=True)   # HMAC du numéro de document, jamais le numéro
    file_sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True)
    checks = models.JSONField(default=list, blank=True)
    risk_level = models.CharField(max_length=8, choices=RISK, default="unknown")
    summary = models.TextField(blank=True, default="")
    ocr_disclaimer = models.CharField(max_length=200, default="Lecture automatique indicative : ce n'est pas une preuve d'authenticité du document.")

    class Meta:
        ordering = ["-created_at", "-id"]


class AIRun(models.Model):
    """Journal des appels aux fournisseurs d'IA : qui, quoi, combien de temps — jamais le contenu."""
    provider = models.CharField(max_length=20)
    task = models.CharField(max_length=40)
    ok = models.BooleanField(default=False)
    sensitive = models.BooleanField(default=False)
    error_code = models.CharField(max_length=40, blank=True, default="")
    latency_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]


class RiskCase(models.Model):
    """Dossier de risque PROPOSÉ par les règles ou l'IA. Statut : l'humain seul le fait évoluer ; la confirmation n'a aucun effet automatique."""
    KINDS = [("duplicate_account", "Doublon potentiel de compte"), ("document_inconsistent", "Document incohérent"), ("identity_incomplete", "Identité incomplète"),
             ("kyc_expired", "Document KYC expiré"), ("abnormal_activity", "Activité anormale"), ("artificial_bookings", "Réservations artificielles possibles")]
    STATUSES = [("open", "À examiner"), ("investigating", "Enquête en cours"), ("confirmed", "Confirmé par l'équipe"), ("dismissed", "Écarté")]
    ACTIVE = ("open", "investigating")

    subject = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="risk_cases")
    related_users = models.JSONField(default=list, blank=True)           # identifiants des autres comptes concernés (doublons, paires)
    kind = models.CharField(max_length=24, choices=KINDS)
    dedupe_key = models.CharField(max_length=80, blank=True, default="")
    priority = models.PositiveSmallIntegerField(default=2)               # 1 faible · 2 moyenne · 3 haute
    status = models.CharField(max_length=14, choices=STATUSES, default="open", db_index=True)
    explanation = models.TextField(blank=True, default="")
    evidence = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=20, default="rules")            # rules | document_analysis
    detected_at = models.DateTimeField(auto_now_add=True)
    last_detected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-priority", "-detected_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["subject", "kind", "dedupe_key"], condition=Q(status__in=("open", "investigating")), name="one_active_risk_per_signal")]


class RiskDecision(models.Model):
    DECISIONS = [("investigate", "Ouvrir une enquête"), ("confirm", "Confirmer (consigné, sans effet automatique)"), ("dismiss", "Écarter"), ("reopen", "Rouvrir")]
    case = models.ForeignKey(RiskCase, on_delete=models.CASCADE, related_name="decisions")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    decision = models.CharField(max_length=12, choices=DECISIONS)
    reason = models.CharField(max_length=1000)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["at", "id"]
