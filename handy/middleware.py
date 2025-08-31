from django.http import HttpResponseForbidden

from handy.models import IPBlacklist


class IPBlacklistMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = self.get_client_ip(request)
        if IPBlacklist.objects.filter(ip_address=ip, is_active=True).exists():
            return HttpResponseForbidden("🚫 Accès refusé : votre IP est sur liste noire.")
        return self.get_response(request)

    def get_client_ip(self, request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip