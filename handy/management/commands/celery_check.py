"""Câblage Celery : chaque tâche planifiée existe, a une cadence valide et part dans une file que le worker écoute.

    python manage.py celery_check                  # contrôle statique (aucun broker requis)
    python manage.py celery_check --db             # + la planification est bien présente dans la base du beat (django_celery_beat)
    python manage.py celery_check --names          # affiche seulement les noms des tâches planifiées (pour scripts/staging/verify.sh)
    python manage.py celery_check --queues default,notifications,celery,flash,otp,bulk   # files écoutées par le worker (défaut : celles du compose)

Une faute de frappe dans le nom d'une tâche, ou une tâche routée vers une file que personne n'écoute, ne produit AUCUNE erreur à
l'exécution : la tâche ne tourne simplement jamais. Cette commande (et son test) le rend visible avant le déploiement.
Code de sortie 1 au moindre défaut."""
from django.conf import settings
from django.core.management.base import BaseCommand


def beat_report(queues):
    """Liste de lignes (tâche, entrée, file, problème|None) pour la planification des settings."""
    from tratra.celery import app

    app.loader.import_default_modules()                    # même découverte que le worker
    registered = set(app.tasks.keys())
    rows = []
    for entry_name, entry in sorted(settings.CELERY_BEAT_SCHEDULE.items()):
        task, problem = entry["task"], None
        schedule = entry.get("schedule")
        if task not in registered:
            problem = "tâche inconnue du registre Celery (nom erroné ou module non importé)"
        elif not isinstance(schedule, (int, float)) and not hasattr(schedule, "is_due"):
            problem = f"cadence illisible ({schedule!r})"
        elif isinstance(schedule, (int, float)) and schedule <= 0:
            problem = "cadence nulle ou négative"
        route = app.amqp.router.route(dict(entry.get("options") or {}), task)
        queue = getattr(route.get("queue"), "name", None) or route.get("queue") or app.conf.task_default_queue
        if problem is None and queue not in queues:
            problem = f"routée vers la file « {queue} » que le worker n'écoute pas ({', '.join(sorted(queues))})"
        rows.append((task, entry_name, queue, problem))
    return rows


class Command(BaseCommand):
    help = "Vérifie le câblage des tâches Celery planifiées (nom, cadence, file écoutée)."

    def add_arguments(self, parser):
        parser.add_argument("--queues", default="default,notifications,celery,flash,otp,bulk", help="Files écoutées par le worker.")
        parser.add_argument("--db", action="store_true", help="Contrôle aussi la base du beat (django_celery_beat).")
        parser.add_argument("--names", action="store_true", help="N'affiche que les noms des tâches planifiées.")

    def handle(self, *args, **opts):
        queues = {q.strip() for q in opts["queues"].split(",") if q.strip()}
        rows = beat_report(queues)
        if opts["names"]:
            for task in sorted({r[0] for r in rows}):
                self.stdout.write(task)
            return
        problems = 0
        for task, entry, queue, problem in rows:
            if problem:
                problems += 1
                self.stderr.write(f"[ERR ] {entry} → {task} : {problem}")
            else:
                self.stdout.write(f"[ ok ] {entry} → {task} (file {queue})")
        if settings.CELERY_TASK_DEFAULT_QUEUE not in queues:
            problems += 1
            self.stderr.write(f"[ERR ] la file par défaut « {settings.CELERY_TASK_DEFAULT_QUEUE} » n'est pas écoutée : aucune tâche sans file explicite ne s'exécuterait")
        if opts["db"]:
            from django_celery_beat.models import PeriodicTask

            stored = set(PeriodicTask.objects.exclude(name__startswith="celery.").values_list("task", flat=True))
            for task in sorted({r[0] for r in rows} - stored):
                problems += 1
                self.stderr.write(f"[ERR ] {task} absente de la base du beat (le conteneur beat a-t-il redémarré après ce déploiement ?)")
        self.stdout.write(f"{len(rows)} tâche(s) planifiée(s), {problems} anomalie(s).")
        if problems:
            raise SystemExit(1)
