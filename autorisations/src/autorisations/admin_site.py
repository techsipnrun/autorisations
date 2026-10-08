"""Regroupement visuel des modèles de l'admin selon leur schéma PostgreSQL."""

from collections import defaultdict

from django.contrib.admin import AdminSite


SCHEMA_LABELS = {
    "instruction": "Instruction",
    "documents": "Documents",
    "avis": "Avis",
    "utilisateurs": "Utilisateurs",
}
SCHEMA_ORDER = tuple(SCHEMA_LABELS)


def get_database_schema(model):
    """Retourne le schéma explicite de ``model._meta.db_table``, ou ``None``."""
    db_table = str(getattr(model._meta, "db_table", "") or "").strip()
    schema, separator, _table = db_table.partition(".")
    if not separator:
        return None

    # Les tables existantes sont de la forme ``\"instruction\".\"dossier\"``.
    # La suppression des guillemets tolère aussi quelques anciennes définitions
    # qui n'en ont pas devant le schéma.
    schema = schema.strip().strip('"').strip()
    return schema or None


def get_schema_label(schema):
    """Libellé humain d'un schéma, sans connaissance des modèles concernés."""
    if schema is None:
        return "Autres"
    return SCHEMA_LABELS.get(schema, schema.replace("_", " ").title())


class SchemaGroupedAdminSite(AdminSite):
    """AdminSite qui ne modifie que la navigation affichée dans l'admin."""

    def get_app_list(self, request, app_label=None):
        # Django construit d'abord la liste depuis son registre et applique les
        # permissions. On ne fait ensuite que déplacer les entrées déjà visibles.
        app_list = super().get_app_list(request, app_label)
        schemas = defaultdict(list)

        for app in app_list:
            for model_data in app["models"]:
                schema = get_database_schema(model_data["model"])
                schemas[schema].append(model_data)

        def schema_sort_key(schema):
            if schema is None:
                return (0, "")
            if schema in SCHEMA_ORDER:
                return (1, SCHEMA_ORDER.index(schema))
            return (2, get_schema_label(schema).casefold())

        grouped_apps = []
        for schema in sorted(schemas, key=schema_sort_key):
            models = sorted(schemas[schema], key=lambda model: model["name"].casefold())
            grouped_apps.append({
                "name": get_schema_label(schema),
                # Les catégories ne sont pas de vraies applications : aucune URL
                # n'est créée ou modifiée pour elles.
                "app_label": f"schema_{schema or 'autres'}",
                "app_url": "",
                "has_module_perms": True,
                "models": models,
            })
        return grouped_apps
