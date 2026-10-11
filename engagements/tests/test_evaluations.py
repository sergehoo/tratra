"""Évaluations périodiques et finales : cadence, anti-abus, réponse unique, masquage, expérience vérifiable."""
from datetime import date, timedelta

import pytest
from django.utils import timezone

from engagements import tasks
from engagements.models import EngagementEvaluation
from engagements.services import contracts, evaluations as ev_svc
from engagements.services.common import EngagementError
from engagements.services.common import moment
from engagements.services.experience import experience_for
from engagements.testing import make_contract, person, pro

pytestmark = pytest.mark.django_db
START = date(2027, 1, 4)


def err(fn, *a, **k):
    with pytest.raises(EngagementError) as e:
        fn(*a, **k)
    return e.value


def good(**over):
    return {"kind": "periodic", "rating": 4, "comment": "Travail soigné, ponctuel et sérieux.", "criteria": {"quality": 5, "punctuality": 4}, **over}


def test_periodic_evaluations_wait_for_seniority_respect_the_interval_and_block_abuse():
    owner, worker, stranger = person("ev_owner"), pro("ev_worker"), person("ev_stranger")
    c = make_contract(owner, worker, start=START, months=36)
    tasks.run(START)
    assert err(ev_svc.create, c, owner, good(), today=START + timedelta(days=10)).code == "too_early"        # 30 jours minimum
    day = START + timedelta(days=40)
    assert err(ev_svc.create, c, stranger, good(), today=day).status == 404
    assert err(ev_svc.create, c, owner, good(rating=7), today=day).extra["fields"]["rating"]
    for text in ("Appelez-moi au +225 07 00 00 00 01", "Écrivez à moi@exemple.com", "Voir https://arnaque.example/pay"):
        assert err(ev_svc.create, c, owner, good(comment=text), today=day).extra["fields"]["comment"]        # démarchage / hameçonnage
    assert err(ev_svc.create, c, owner, good(criteria={"magie": 5}), today=day).extra["fields"]["criteria"]
    first = ev_svc.create(c, owner, good(), today=day)
    assert first.subject_id == worker.id and first.author_id == owner.id
    EngagementEvaluation.objects.filter(pk=first.pk).update(created_at=moment(day))                  # dates simulées cohérentes
    assert err(ev_svc.create, c, owner, good(), today=day + timedelta(days=1)).code in ("too_soon", "already_evaluated")
    assert err(ev_svc.create, c, owner, good(), today=day + timedelta(days=20)).code == "too_soon"           # intervalle de 30 jours (évaluation mensuelle)
    EngagementEvaluation.objects.filter(pk=first.pk).update(created_at=moment(day - timedelta(days=91)))
    second = ev_svc.create(c, owner, good(rating=5), today=day + timedelta(days=95))
    assert second.period_key != first.period_key
    back = ev_svc.create(c, worker, good(rating=5, comment="Donneur d'ordre clair et respectueux."), today=day)        # l'autre partie évalue aussi
    assert back.subject_id == owner.id
    assert err(ev_svc.create, c, owner, {"kind": "final", "rating": 4}, today=day).code == "not_ended"


def test_edit_window_single_reply_report_and_back_office_hiding():
    owner, worker = person("eh_owner"), pro("eh_worker")
    c = make_contract(owner, worker, start=START, months=36)
    tasks.run(START)
    ev = ev_svc.create(c, owner, good(), today=START + timedelta(days=40))
    assert err(ev_svc.update, ev, worker, {"rating": 1}).status == 403
    assert ev_svc.update(ev, owner, {"rating": 3}).rating == 3
    assert err(ev_svc.reply, ev, owner, "Merci").status == 403                                       # seule la personne évaluée répond
    ev_svc.reply(ev, worker, "Merci pour ce retour, je tiens compte des remarques.")
    assert err(ev_svc.reply, ev, worker, "Un second mot").code == "already_replied"
    EngagementEvaluation.objects.filter(pk=ev.pk).update(edit_until=timezone.now() - timedelta(minutes=1))
    assert err(ev_svc.update, ev, owner, {"rating": 5}).code == "locked"
    assert ev_svc.report(ev, worker, "Cette évaluation est mensongère.").pk == ev_svc.report(ev, worker, "Cette évaluation est mensongère.").pk   # idempotent
    assert err(ev_svc.report, ev, person("eh_stranger"), "Je signale quelque chose").status == 404
    assert ev_svc.summary_for(worker)["count"] == 1 and ev_svc.summary_for(worker)["average"] is None     # moyenne publiée seulement à partir de 3
    EngagementEvaluation.objects.filter(pk=ev.pk).update(is_hidden=True)
    assert ev_svc.summary_for(worker)["count"] == 0                                                  # masquée : exclue des statistiques


def test_final_evaluation_only_after_the_end_inside_the_window_and_experience_is_verifiable():
    owner, worker = person("fe_owner"), pro("fe_worker")
    c = make_contract(owner, worker, start=START, months=6)
    assert experience_for(worker, today=START)["contracts_active"] == 1                                 # compte dès l'activation (début atteint)
    assert experience_for(pro("fe_nobody"))["contracts_active"] == 0
    tasks.run(START)
    assert experience_for(worker, today=START + timedelta(days=100))["months_total"] == 3
    end = c.end_date + timedelta(days=1)
    tasks.run(end)
    c.refresh_from_db()
    assert c.status == "completed"
    f = ev_svc.create(c, owner, {"kind": "final", "rating": 5, "comment": "Six mois sans accroc."}, today=end + timedelta(days=2))
    assert f.period_key == "final"
    assert err(ev_svc.create, c, owner, {"kind": "final", "rating": 5}, today=end + timedelta(days=3)).code == "already_evaluated"
    assert err(ev_svc.create, c, worker, {"kind": "final", "rating": 5}, today=end + timedelta(days=90)).code == "window_closed"
    xp = experience_for(worker, today=end + timedelta(days=3))
    assert xp["contracts_completed"] == 1 and xp["months_total"] == 6 and xp["distinct_principals"] == 1 and xp["source"].startswith("contrats acceptés")
    assert "amount" not in str(xp) and owner.username not in str(xp)                                 # ni montant ni identité du donneur d'ordre
    never = make_contract(person("fe_owner2"), pro("fe_worker2"), start=START + timedelta(days=400), today=START, months=6)    # accepté mais jamais commencé
    assert err(ev_svc.create, never, never.principal, {"kind": "periodic", "rating": 5}, today=START).code == "not_started"
