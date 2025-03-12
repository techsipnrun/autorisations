from django import template

register = template.Library()

@register.filter(name='has_group')
def has_group(user, group_name):
    """ Vérifie si un utilisateur appartient à un groupe spécifique """
    return user.groups.filter(name=group_name).exists()
