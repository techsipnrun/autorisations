from django.contrib.admin.apps import AdminConfig


class SchemaGroupedAdminConfig(AdminConfig):
    """Utilise le regroupement par schéma pour le site ``admin.site`` global."""

    default_site = "autorisations.admin_site.SchemaGroupedAdminSite"
