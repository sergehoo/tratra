"""Câblage Celery : une tâche planifiée avec un nom erroné, une cadence invalide ou une file que le worker n'écoute pas ne planterait
jamais — elle ne tournerait simplement pas. Ces tests le rendent visible avant le déploiement."""
import re
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from handy.management.commands.celery_check import beat_report

pytestmark = pytest.mark.django_db       # l'import des modules de tâches (djstripe, beat) interroge la base
ROOT = Path(__file__).resolve().parents[1]
# Tâches périodiques indispensables au produit : si l'une disparaît de la planification, une fonctionnalité s'arrête en silence.
REQUIRED = {
    "trust.tasks.reevaluate_all_profiles",
    "business.tasks.run_preventive_plans",
    "announcements.tasks.tick",
    "continuity.tasks.purge_idempotency",
    "engagements.tasks.tick",
    "handy.tasks.reconcile_provider_payments",
    "live.tasks.purge_positions",
}


def compose_queues(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    found = re.findall(r"celery -A tratra worker[^\n]*--queues=([\w,]+)", text)
    assert found, f"{name} : aucun worker Celery avec --queues"
    return {q for group in found for q in group.split(",")}


def test_every_scheduled_task_is_registered_valid_and_routed_to_a_queue_the_worker_listens_to():
    rows = beat_report(compose_queues("docker-compose.staging.yml"))
    assert rows and [(task, problem) for task, _, _, problem in rows if problem] == []


def test_the_required_periodic_tasks_are_all_scheduled():
    assert REQUIRED <= {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}


def test_both_compose_files_listen_to_the_default_queue_and_the_notification_queue():
    for name in ("docker-compose.yml", "docker-compose.staging.yml"):
        assert {settings.CELERY_TASK_DEFAULT_QUEUE, "notifications"} <= compose_queues(name), name


def test_both_compose_files_listen_to_every_push_queue():
    """Push courants (« default »), missions Flash (« flash ») et diffusions de masse (« bulk ») : une file que personne n'écoute = des
    push jamais envoyés."""
    from handy import notifications

    queues = {notifications.push_queue(category) for category in notifications.CHANNEL_BY_CATEGORY}
    assert queues == {"default", "flash", "bulk"}
    for name in ("docker-compose.yml", "docker-compose.staging.yml"):
        assert queues <= compose_queues(name), name


def test_the_check_detects_a_misspelt_task_and_an_unlistened_queue(settings):
    settings.CELERY_BEAT_SCHEDULE = {**settings.CELERY_BEAT_SCHEDULE, "typo": {"task": "engagements.tasks.tik", "schedule": 60.0},
                                     "never": {"task": "announcements.tasks.tick", "schedule": 0}}
    problems = {entry: problem for _, entry, _, problem in beat_report({"default"}) if problem}
    assert "inconnue" in problems["typo"] and "nulle" in problems["never"]
    with pytest.raises(SystemExit):
        call_command("celery_check")


def test_the_command_passes_on_the_real_schedule_and_lists_names(capsys):
    call_command("celery_check", "--queues", "default,notifications,celery,flash,otp,bulk")
    assert "0 anomalie(s)" in capsys.readouterr().out
    call_command("celery_check", "--names")
    assert REQUIRED <= set(capsys.readouterr().out.split())
