"""Compte de relecture des boutiques d'applications : client ordinaire, mot de passe tiré au hasard et affiché une fois."""
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from handy.models import User

pytestmark = pytest.mark.django_db


def _run(*args):
    out = StringIO()
    call_command("create_review_account", *args, stdout=out)
    text = out.getvalue()
    password = text.split("Mot de passe (affiché une seule fois) : ")[1].strip()
    return text, password


def test_cree_un_client_ordinaire_dont_le_mot_de_passe_fonctionne():
    text, password = _run()
    user = User.objects.get(username="play_review")
    assert user.check_password(password)
    assert user.user_type == "client" and user.is_active and user.is_verified
    assert not user.is_staff and not user.is_superuser
    assert not hasattr(user, "handyman_profile")
    assert user.terms_accepted_at is not None
    assert "créé" in text


def test_relancer_change_le_mot_de_passe_sans_dupliquer_le_compte():
    _, first = _run()
    _, second = _run()
    assert first != second
    assert User.objects.filter(username="play_review").count() == 1
    user = User.objects.get(username="play_review")
    assert user.check_password(second) and not user.check_password(first)


def test_refuse_un_numero_deja_utilise_par_un_autre_compte():
    User.objects.create_user(username="vrai_membre", password="Xx-123456-aa", phone="+2250700000199")
    with pytest.raises(CommandError):
        _run()
    assert not User.objects.filter(username="play_review").exists()


def test_refuse_un_numero_mal_forme():
    with pytest.raises(CommandError):
        _run("--phone", "0700000199")
