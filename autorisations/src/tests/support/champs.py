"""Fabriques minimales de champs/dossiers, sans accès à la BDD."""
from types import SimpleNamespace
from unittest.mock import MagicMock


def creer_champ(type_champ, nom, valeur=None, **attributs):
    """Construit un champ minimal sans dépendre de la base de données."""
    valeurs = {
        "id": attributs.pop("id", 1),
        "id_champ": SimpleNamespace(
            id_champ_type=SimpleNamespace(type=type_champ),
            nom=nom,
        ),
        "valeur": valeur,
        "geometrie": None,
        "geometrie_modif": None,
        "id_document": None,
    }
    valeurs.update(attributs)
    return SimpleNamespace(**valeurs)


def creer_dossier(*champs, numero=30769307, emplacement="dossiers/30769307"):
    gestionnaire = MagicMock()
    gestionnaire.select_related.return_value.order_by.return_value = list(champs)
    return SimpleNamespace(
        numero=numero,
        emplacement=emplacement,
        dossierchamp_set=gestionnaire,
    )


