"""Registre des modules du Back-Office : un module n'apparaît que si le rôle de l'utilisateur lui donne le droit requis.
Le menu n'est qu'un confort : chaque endpoint refuse de toute façon ce que le rôle n'autorise pas."""
from backoffice import rbac

# (identifiant, libellé, droit requis, icône, chemin web)
MODULES = [
    ("dashboard", "Tableau de bord", "dashboard.view", "layout-dashboard", "/backoffice"),
    ("users", "Utilisateurs", "users.view", "users", "/backoffice/users"),
    ("kyc", "Vérification KYC", "kyc.review", "shield-check", "/backoffice/kyc"),
    ("trust", "Tratra Trust", "trust.manage", "award", "/backoffice/trust"),
    ("tratra_id", "Tratra ID", "tratra_id.manage", "id-card", "/backoffice/tratra-id"),
    ("services", "Services", "services.moderate", "briefcase", "/backoffice/services"),
    ("bookings", "Réservations et litiges", "bookings.view", "calendar-check", "/backoffice/bookings"),
    ("flash", "Tratra Flash", "bookings.view", "zap", "/backoffice/flash"),
    ("live", "Suivi en direct", "live.view", "map-pin", "/backoffice/live"),
    ("reviews", "Avis", "reviews.moderate", "star", "/backoffice/reviews"),
    ("business", "Tratra Business", "business.manage", "building-2", "/backoffice/business"),
    ("engagements", "Engagements", "engagements.view", "file-signature", "/backoffice/engagements"),
    ("finance", "Finances", "finance.view", "wallet", "/backoffice/finance"),
    ("messages", "Messagerie", "messages.send", "message-square", "/backoffice/messages"),
    ("announcements", "Annonces", "announcements.manage", "megaphone", "/backoffice/announcements"),
    ("campaigns", "Engagement automatisé", "announcements.manage", "sparkles", "/backoffice/campaigns"),
    ("notifications", "Notifications", "notifications.view", "bell", "/backoffice/notifications"),
    ("continuity", "Continuité", "continuity.view", "refresh-cw", "/backoffice/continuity"),
    ("support", "Support", "support.manage", "life-buoy", "/backoffice/support"),
    ("analytics", "Statistiques et exports", "analytics.view", "bar-chart-3", "/backoffice/analytics"),
    ("settings", "Réglages", "settings.manage", "settings", "/backoffice/settings"),
    ("security", "Sécurité et audit", "security.manage", "lock", "/backoffice/security"),
]


def modules_for(user):
    perms = rbac.user_permissions(user)
    return [{"id": i, "label": label, "permission": perm, "icon": icon, "path": path}
            for i, label, perm, icon, path in MODULES if perm in perms]
