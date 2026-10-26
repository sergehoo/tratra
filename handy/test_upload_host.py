"""Hôte d'envoi direct des fichiers de l'application (UPLOAD_HOST, « DNS seulement », hors Cloudflare).

Sur certains Wi-Fi, les envois de fichiers d'un téléphone vers Cloudflare sont coupés au bout de 15 s alors que le même envoi passe en
direct vers le serveur. L'application envoie donc ses fichiers par cet hôte, qui sert la même API — mais seulement ses envois de fichiers :
connexion, codes SMS et tout le reste y répondent 404 et restent derrière Cloudflare. Une requête admise est traitée sous l'hôte de l'API."""
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.urls import resolve

from announcements.test_announcements import account, api
from handy.security import UPLOAD_PATHS, UploadHostMiddleware, is_upload_request
from handy.test_deploy_config import _GOOD_ENV, _check_env_module, _compose, _labels, _load_prod_settings, _write
from handy.testing import make_jpeg
from statuses.models import Status

UPLOAD, API = "upload.tratra.test", "api.tratra.test"
HOSTS = override_settings(UPLOAD_HOST=UPLOAD, API_PUBLIC_HOST=API, ALLOWED_HOSTS=["testserver", API, UPLOAD])

# Un exemple par envoi de fichier de l'application (lib/… : statuts, messages, KYC, biométrie, justificatifs, espèces, avis, photos,
# engagements) : chacun doit être admis ET correspondre à une vraie route de l'API.
APP_UPLOADS = [
    ("POST", "/handy/statuses/"),
    ("POST", "/handy/me/conversations/12/send/"),
    ("POST", "/handy/me/kyc/capture/"),
    ("POST", "/handy/kyc/biometric/sessions/3/captures/"),
    ("POST", "/handy/handyman-docs/"),
    ("POST", "/handy/bookings/7/payment/cash/"),
    ("POST", "/handy/reviews/5/photos/"),
    ("PATCH", "/handy/users/9/"),
    ("PATCH", "/handy/handymen/4/"),
    ("POST", "/handy/engagements/installments/8/payments/"),
    ("POST", "/handy/engagements/installments/8/lines/"),
]


def _request(method, path, host=UPLOAD, content_type="multipart/form-data; boundary=x"):
    return RequestFactory().generic(method, path, b"--x--", content_type=content_type, HTTP_HOST=host)   # sans corps, pas de Content-Type


@pytest.mark.parametrize("method,path", APP_UPLOADS)
def test_every_app_file_upload_is_admitted_and_points_to_a_real_endpoint(method, path):
    resolve(path)                                                     # route réelle (sinon Resolver404)
    with HOSTS:
        assert is_upload_request(_request(method, path))
        assert not is_upload_request(_request(method, path, content_type="application/json"))   # JSON : jamais par cet hôte


@pytest.mark.parametrize("method,path", [
    ("POST", "/handy/auth/login/"), ("POST", "/handy/auth/refresh/"), ("POST", "/handy/auth/otp/request/"), ("GET", "/handy/statuses/feed/"),
    ("GET", "/handy/users/9/"), ("DELETE", "/handy/statuses/4/"), ("POST", "/handy/backoffice/statuses/4/remove/"), ("GET", "/admin/"),
])
def test_everything_else_is_refused_on_the_upload_host_even_as_multipart(method, path):
    with HOSTS:
        response = UploadHostMiddleware(lambda r: HttpResponse("vue atteinte"))(_request(method, path))
    assert response.status_code == 404 and b"upload_host_only" in response.content and response["X-Upload-Host"] == "refused"


def test_an_admitted_upload_is_handled_under_the_api_host():
    seen = {}

    def view(request):
        seen["host"] = request.get_host()
        seen["link"] = request.build_absolute_uri("/handy/statuses/1/")
        return HttpResponse("ok")

    with HOSTS:
        assert UploadHostMiddleware(view)(_request("POST", "/handy/statuses/")).status_code == 200
        assert UploadHostMiddleware(lambda r: HttpResponse("ok"))(_request("GET", "/healthz")).status_code == 200   # vérification de la route
    assert seen == {"host": API, "link": f"http://{API}/handy/statuses/1/"}


def test_the_api_host_and_a_disabled_upload_host_are_untouched():
    with HOSTS:
        assert UploadHostMiddleware(lambda r: HttpResponse("vue"))(_request("POST", "/handy/auth/login/", host=API)).content == b"vue"
    with override_settings(UPLOAD_HOST=""):
        assert UploadHostMiddleware(lambda r: HttpResponse("vue"))(_request("GET", "/handy/statuses/feed/", host=UPLOAD)).content == b"vue"


@pytest.mark.django_db
def test_a_photo_status_published_through_the_upload_host(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")
    u = account("upload_direct")
    client_id = str(uuid.uuid4())
    with HOSTS:
        r = api(u).post("/handy/statuses/", {"text": "Envoyé en direct", "client_id": client_id, "file": SimpleUploadedFile("photo.jpg", make_jpeg(), content_type="image/jpeg")}, format="multipart",
                        HTTP_HOST=UPLOAD)
        assert r.status_code == 201, r.content[:300]
        feed = api(u).get("/handy/statuses/feed/", HTTP_HOST=UPLOAD)
        assert feed.status_code == 404                                   # lire le fil : par l'API, jamais par l'hôte d'envoi
        assert api(u).get("/handy/statuses/feed/", HTTP_HOST=API).status_code == 200
    status = Status.objects.get(client_id=client_id)
    assert status.kind == Status.PHOTO and status.media


def test_compose_routes_the_upload_host_to_the_api_container_with_its_protections():
    labels = dict(label.split("=", 1) for label in _labels(_compose("docker-compose.yml")["services"]["tratraweb"]))
    assert labels["traefik.http.routers.tratraupload.rule"] == "Host(`${UPLOAD_HOST}`)"
    assert labels["traefik.http.routers.tratraupload.service"] == labels["traefik.http.routers.tratraweb.service"] == "tratraweb-svc"
    assert labels["traefik.http.routers.tratraupload.entrypoints"] == "websecure"
    assert labels["traefik.http.routers.tratraupload.tls.certresolver"] == labels["traefik.http.routers.tratraweb.tls.certresolver"]
    assert "tratraweb-rl@docker" in labels["traefik.http.routers.tratraupload.middlewares"]


def test_check_env_explains_a_missing_or_misused_upload_host(tmp_path):
    module = _check_env_module()

    def problems(extra):
        errors, warns = module.check(module.parse(_write(tmp_path, _GOOD_ENV + extra)))
        return {v for v, _ in errors if v == "UPLOAD_HOST"}, {v for v, _ in warns if v == "UPLOAD_HOST"}

    assert problems("") == (set(), {"UPLOAD_HOST"})                                  # absent : avertissement, pas d'échec
    assert problems("UPLOAD_HOST=upload.tratra.test\n") == (set(), set())
    assert problems("UPLOAD_HOST=https://upload.tratra.test\n")[0] == {"UPLOAD_HOST"}
    assert problems("UPLOAD_HOST=api.tratra.test\n")[0] == {"UPLOAD_HOST"}          # jamais l'hôte de l'API lui-même


def test_production_accepts_the_upload_host_without_listing_it_by_hand():
    code = ("import django; django.setup(); from django.conf import settings; "
            "print('HOSTS=' + ','.join(settings.ALLOWED_HOSTS)); print('API=' + settings.API_PUBLIC_HOST)")
    r = _load_prod_settings(code=code, UPLOAD_HOST="Upload.Tratra.Test", tratraweb_HOST="api.tratra.test",
                            MINIO_ENABLED="True", AWS_ACCESS_KEY_ID="k", AWS_SECRET_ACCESS_KEY="s", AWS_STORAGE_BUCKET_NAME="b",
                            KYC_STORAGE_BUCKET_NAME="k", AWS_S3_ENDPOINT_URL="https://s3.example.test", PUBLIC_WEB_URL="https://app.example.test")
    assert r.returncode == 0, r.stderr[-400:]
    assert "upload.tratra.test" in r.stdout.split("HOSTS=")[1].split("\n")[0].split(",")
    assert "API=api.tratra.test" in r.stdout
