"""Anti-fraude biométrique : alertes EXPLICABLES pour le Back-Office (jamais de décision automatique, jamais de reconnaissance faciale entre comptes).

Ce qui est signalé : tentatives répétées, images rejouées (même fichier dans plusieurs sessions), enchaînement trop rapide, indices techniques
du fournisseur (écran, masque, injection). Une ressemblance de visage entre deux comptes n'est JAMAIS calculée ni utilisée."""
from datetime import timedelta

from django.utils import timezone

from biometrics.models import BiometricSession
from intelligence import risk

REPEAT_LIMIT = 3          # échecs ou résultats non concluants en 24 h


def after_session(session: BiometricSession) -> None:
    user_id = session.user_id
    since = timezone.now() - timedelta(days=1)
    bad = BiometricSession.objects.filter(user_id=user_id, created_at__gte=since, outcome__in=("failed", "inconclusive")).count()
    if bad >= REPEAT_LIMIT:
        risk.propose(user_id, "biometric_attempts", 3 if bad >= REPEAT_LIMIT + 2 else 2,
                     f"{bad} vérifications faciales échouées ou non concluantes en 24 heures. À examiner : difficultés techniques ou tentatives répétées.",
                     {"attempts_24h": bad}, dedupe_key="repeated", source="biometrics")
    bypass = [a for a in session.anomalies if a in ("capture_reused_elsewhere", "identical_frames", "too_fast") or a.startswith("provider:")]
    if bypass:
        reused = "capture_reused_elsewhere" in bypass
        risk.propose(user_id, "liveness_bypass", 3 if reused or any(a.startswith("provider:") for a in bypass) else 2,
                     "Indices techniques de contournement possible du liveness : " + ", ".join(bypass) + ". Indicatif, jamais une preuve : à vérifier par un humain.",
                     {"anomalies": bypass, "session": session.pk}, dedupe_key=f"session:{session.pk}", source="biometrics")
    if session.outcome == "provider_error":
        risk.propose(user_id, "biometric_technical", 1, "Le fournisseur de vérification faciale était indisponible : dossier à traiter par revue humaine.",
                     {"session": session.pk}, dedupe_key=f"provider:{session.pk}", source="biometrics")
