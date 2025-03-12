from rest_framework import permissions

class PeutUtiliserMethodeAvis(permissions.BasePermission):
    """
    Autorise uniquement les utilisateurs ayant le rôle "avis_modification" à modifier.
    """
    
    def has_permission(self, request, view):
        # Tous les utilisateurs connectés peuvent voir les avis
        if request.method in permissions.SAFE_METHODS:
            return True
        # Seuls les utilisateurs avec le rôle avis_modification peuvent modifier
        return request.user.groups.filter(name="avis_modification").exists()
