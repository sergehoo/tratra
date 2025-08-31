# templatetags/custom_filters.py
from django import template

register = template.Library()


@register.filter
def percentage_of(value, max_value):
    """Convertit une valeur en pourcentage d'une valeur maximale"""
    if not max_value or value is None:
        return 0
    return min(100, int((value / max_value) * 100))


@register.filter
def star_percentage(value):
    """Convertit une note (0-5) en pourcentage pour l'affichage des étoiles"""
    if value is None:
        return 100  # Valeur par défaut
    return min(100, int((value / 5) * 100))


@register.simple_tag(takes_context=True)
def param_replace(context, **kwargs):
    """
    Remplace les paramètres GET tout en conservant les paramètres existants
    """
    params = context['request'].GET.copy()
    for key, value in kwargs.items():
        if value is None:
            if key in params:
                del params[key]
        else:
            params[key] = value
    return params.urlencode()
