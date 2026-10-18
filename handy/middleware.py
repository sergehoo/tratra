from django.http import HttpResponseForbidden

from handy.models import IPBlacklist
from handy.security import client_ip


class IPBlacklistMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = self.get_client_ip(request)
        if IPBlacklist.objects.filter(ip_address=ip, is_active=True).exists():
            return HttpResponseForbidden("🚫 Accès refusé : votre IP est sur liste noire.")
        return self.get_response(request)

    def get_client_ip(self, request):
        # Jamais l'entrée la plus à gauche de X-Forwarded-For : elle est écrite par le client (contournement de la liste noire).
        return client_ip(request)