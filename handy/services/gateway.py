# payments/gateway.py
from abc import ABC, abstractmethod

class Provider(ABC):
    @abstractmethod
    def create(self, booking, amount_xof: int) -> dict: ...
    @abstractmethod
    def capture(self, provider_ref: str) -> dict: ...
    @abstractmethod
    def refund(self, provider_ref: str, amount_xof: int) -> dict: ...

class OrangeMoney(Provider):
    def create(self, booking, amount_xof):
        # appel API OM -> retourne redirect_url / otp_ref
        return {"provider":"om","provider_ref":"om_tx_...", "redirect_url":"https://..."}

# views.py (webhook)
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from handy.models import Payment, PaymentLog

class PaymentWebhook(APIView):
    authentication_classes = []  # HMAC header
    permission_classes = []
    def post(self, request, provider):
        data = request.data
        provider_ref = data["provider_ref"]
        new_status = data["status"]
        with transaction.atomic():
            p = Payment.objects.select_for_update().get(transaction_id=provider_ref)
            old = p.status
            if old != new_status:
                p.status = new_status
                p.save(update_fields=["status","updated_at"])
                PaymentLog.objects.create(payment=p, previous_status=old, new_status=new_status, notes=f"prov={provider}")
        return Response({"ok": True})