from django.urls import path

from biometrics import api

urlpatterns = [
    path("kyc/biometric/", api.biometric_state, name="biometric-state"),
    path("kyc/biometric/consent/", api.biometric_consent, name="biometric-consent"),
    path("kyc/biometric/sessions/", api.biometric_session, name="biometric-session"),
    path("kyc/biometric/sessions/<int:pk>/captures/", api.biometric_capture, name="biometric-capture"),
    path("kyc/biometric/sessions/<int:pk>/submit/", api.biometric_submit, name="biometric-submit"),
    path("kyc/biometric/human-review/", api.biometric_human_review, name="biometric-human-review"),
]
