# handy/management/commands/load_service_categories.py

from django.core.management.base import BaseCommand
from handy.models import ServiceCategory
from django.utils.text import slugify


class Command(BaseCommand):
    help = "Charge les catégories de services prédéfinies dans la base."

    def handle(self, *args, **kwargs):
        categories = [
            # Services de construction et rénovation
            {"name": "Plomberie", "icon": "fas fa-faucet",
             "description": "Installation et réparation de systèmes de plomberie"},
            {"name": "Électricité", "icon": "fas fa-bolt", "description": "Installation électrique et dépannage"},
            {"name": "Peinture", "icon": "fas fa-paint-roller",
             "description": "Travaux de peinture intérieure et extérieure"},
            {"name": "Menuiserie", "icon": "fas fa-tree", "description": "Fabrication et pose d'éléments en bois"},
            {"name": "Maçonnerie", "icon": "fas fa-home",
             "description": "Travaux de construction et rénovation en maçonnerie"},
            {"name": "Carrelage", "icon": "fas fa-border-style", "description": "Pose et réparation de carrelage"},
            {"name": "Toiture", "icon": "fas fa-house-damage", "description": "Réparation et installation de toitures"},
            {"name": "Climatisation", "icon": "fas fa-wind",
             "description": "Installation et entretien de systèmes de climatisation"},

            # Services d'entretien et ménage
            {"name": "Ménage", "icon": "fas fa-broom", "description": "Services de nettoyage et entretien domestique"},
            {"name": "Jardinage", "icon": "fas fa-seedling", "description": "Entretien de jardins et espaces verts"},
            {"name": "Paysagisme", "icon": "fas fa-leaf", "description": "Aménagement et conception d'espaces verts"},
            {"name": "Entretien piscine", "icon": "fas fa-swimming-pool",
             "description": "Nettoyage et entretien de piscines"},

            # Services techniques
            {"name": "Serrurerie", "icon": "fas fa-key", "description": "Dépannage et installation de serrures"},
            {"name": "Vitrerie", "icon": "fas fa-window-maximize", "description": "Pose et réparation de vitres"},
            {"name": "Chauffage", "icon": "fas fa-fire",
             "description": "Installation et entretien de systèmes de chauffage"},
            {"name": "Isolation", "icon": "fas fa-igloo", "description": "Travaux d'isolation thermique et acoustique"},

            # Services spécialisés
            {"name": "Ébénisterie", "icon": "fas fa-chair", "description": "Fabrication et restauration de meubles"},
            {"name": "Ferronnerie", "icon": "fas fa-hammer", "description": "Travaux de métallerie et soudure"},
            {"name": "Plâtrerie", "icon": "fas fa-trowel", "description": "Pose de plaques de plâtre et finitions"},
            {"name": "Sol PVC", "icon": "fas fa-border-all", "description": "Pose de revêtements de sol en PVC"},

            # Services de montage et installation
            {"name": "Montage meuble", "icon": "fas fa-couch", "description": "Assemblage et installation de meubles"},
            {"name": "Installation électroménager", "icon": "fas fa-blender",
             "description": "Pose et raccordement d'appareils électroménagers"},
            {"name": "Pose parquet", "icon": "fas fa-border-style",
             "description": "Installation de parquets et sols en bois"},

            # Services divers
            {"name": "Déménagement", "icon": "fas fa-truck-moving", "description": "Aide au déménagement et transport"},
            {"name": "Débarras", "icon": "fas fa-trash-alt", "description": "Vidage de maisons et locaux"},
            {"name": "Bricolage", "icon": "fas fa-tools",
             "description": "Petits travaux de réparation et d'amélioration"},
            {"name": "Nettoyage après travaux", "icon": "fas fa-broom",
             "description": "Nettoyage complet après rénovation"},

            # Services extérieurs
            {"name": "Clôture", "icon": "fas fa-fence", "description": "Installation et réparation de clôtures"},
            {"name": "Terrasse", "icon": "fas fa-umbrella-beach",
             "description": "Construction et entretien de terrasses"},
            {"name": "Allée jardin", "icon": "fas fa-road", "description": "Création d'allées et chemins de jardin"},

            # Services de réparation
            {"name": "Réparation électroménager", "icon": "fas fa-toolbox",
             "description": "Dépannage d'appareils électroménagers"},
            {"name": "Réparation smartphone", "icon": "fas fa-mobile-alt",
             "description": "Réparation de téléphones portables et tablettes"},
            {"name": "Réparation ordinateur", "icon": "fas fa-laptop",
             "description": "Dépannage informatique et réparation PC"},

            # Services automobiles
            {"name": "Mécanique auto", "icon": "fas fa-car", "description": "Entretien et réparation automobile"},
            {"name": "Carrosserie", "icon": "fas fa-car-crash",
             "description": "Réparation de carrosserie et peinture auto"},
            {"name": "Lavage auto", "icon": "fas fa-car-side",
             "description": "Nettoyage intérieur et extérieur de véhicules"},

            # Services événementiels
            {"name": "Service traiteur", "icon": "fas fa-utensils",
             "description": "Préparation et service de repas pour événements"},
            {"name": "Animation événement", "icon": "fas fa-music",
             "description": "Animation et divertissement pour événements"},
            {"name": "Décoration événement", "icon": "fas fa-glass-cheers",
             "description": "Décoration et aménagement d'espaces événementiels"},

            # Services de garde
            {"name": "Garde d'enfants", "icon": "fas fa-baby", "description": "Garde d'enfants à domicile"},
            {"name": "Garde d'animaux", "icon": "fas fa-paw",
             "description": "Garde et promenade d'animaux domestiques"},
            {"name": "Surveillance maison", "icon": "fas fa-home",
             "description": "Surveillance de résidence pendant les absences"},

            # Services de confort
            {"name": "Chauffeur privé", "icon": "fas fa-car",
             "description": "Service de conduite et transport personnel"},
            {"name": "Cours particulier", "icon": "fas fa-book-open",
             "description": "Soutien scolaire et cours à domicile"},
            {"name": "Assistance informatique", "icon": "fas fa-laptop-code",
             "description": "Aide et formation en informatique"},
        ]

        for cat in categories:
            obj, created = ServiceCategory.objects.get_or_create(
                name=cat["name"],
                defaults={
                    "slug": slugify(cat["name"]),
                    "description": cat["description"],
                    "icon": cat["icon"],
                    "is_active": True,
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"✅ Créé : {obj.name}"))
            else:
                self.stdout.write(f"🔄 Déjà existant : {obj.name}")

        self.stdout.write(self.style.SUCCESS(f"✔️ Chargement de {len(categories)} catégories terminé."))