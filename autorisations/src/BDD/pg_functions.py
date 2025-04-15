import logging
import django
import os
from django.db import connection
import requests
from typing import Type, Tuple, Optional

from autorisations.models.models_instruction import Demarche

# #Définir le module de paramètres Django
# os.environ.setdefault("DJANGO_SETTINGS_MODULE", "instructionDS.settings")
# # Initialiser Django
# django.setup()


logger = logging.getLogger('ORM_DJANGO')

# Fonction générique pour récupérer un objet par son champ unique
def get_object(model, **kwargs):
    """
    Retourne un objet d'un modèle Django selon les critères donnés.
    :param model: Classe du modèle Django (ex: Agent, Demarche)
    :param kwargs: Critères de recherche (ex: email="example@example.com")
    :return: Instance du modèle ou None
    """
    try:
        obj = model.objects.get(**kwargs)
        # logging.info(f"{model.__name__} trouvé : {obj}")
        return obj
    except model.DoesNotExist:
        logging.warning(f"Aucun {model.__name__} trouvé avec les critères : {kwargs}")
        return None
    except Exception as e:
        logging.error(f"Erreur lors de la récupération d'un {model.__name__} : {e}")
        return None



def get_or_create_object(
        model: Type,
        search_kwargs: dict,
        defaults_kwargs: Optional[dict] = None,
        raise_exception: bool = False
    ) -> Tuple[object, bool]:
    """
    Récupère ou crée un objet d’un modèle Django selon des critères donnés.

    :param model: Classe du modèle Django (ex: Demarche, Agent)
    :param search_kwargs: Dictionnaire des champs pour la recherche (ex: {"numero": "DEM-123"})
    :param defaults_kwargs: Champs à utiliser si création (ex: {"libelle": "Nouvelle Démarche"})
    :param raise_exception: Si True, relance l'exception en cas d'erreur
    :return: Tuple (objet, created) — created=True si objet créé, False sinon
    """
    try:
        obj, created = model.objects.get_or_create(
            **search_kwargs,
            defaults=defaults_kwargs or {}
        )
        action = "créé" if created else "trouvé"
        logger.info(f"{model.__name__} {action} avec {search_kwargs}")
        return obj, created
    except Exception as e:
        logger.error(f"Erreur lors du get_or_create sur {model.__name__} : {e}")
        if raise_exception:
            raise
        return None, False



# Fonction générique pour récupérer tous les objets d'un modèle
def get_all_objects(model):
    """
    Retourne tous les objets d'un modèle Django.
    :param model: Classe du modèle Django (ex: Agent, Demarche)
    :return: Liste d'instances du modèle
    """
    try:
        objs = model.objects.all()
        logging.info(f"{objs.count()} {model.__name__}(s) récupéré(s).")
        return list(objs)
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des {model.__name__}(s) : {e}")
        return []


def delete_object(model, **kwargs):
    """
    Supprime un objet d'un modèle Django selon les critères donnés.
    :param model: Classe du modèle Django (ex: Agent, Demarche)
    :param kwargs: Critères de recherche (ex: email="example@example.com")
    :return: True si l'objet a été supprimé, False sinon.
    """
    try:
        obj = model.objects.get(**kwargs)
        obj.delete()
        logging.info(f"{model.__name__} supprimé : {kwargs}")
        return True
    except model.DoesNotExist:
        logging.warning(f"Aucun {model.__name__} trouvé avec les critères : {kwargs}")
        return False
    except Exception as e:
        logging.error(f"Erreur lors de la suppression d'un {model.__name__} : {e}")
        return False

def delete_all_objects(model):
    """
    Supprime tous les objets d'un modèle Django.
    :param model: Classe du modèle Django (ex: Agent, Demarche)
    :return: Le nombre d'objets supprimés.
    """
    try:
        count, _ = model.objects.all().delete()
        logging.info(f"Tous les objets {model.__name__} supprimés ({count} supprimés).")
        return count
    except Exception as e:
        logging.error(f"Erreur lors de la suppression des objets {model.__name__} : {e}")
        return 0
    

def create_object(model, **kwargs):
    """
    Crée un nouvel objet pour un modèle Django.
    :param model: Classe du modèle Django (ex: Agent, Demarche)
    :param kwargs: Champs et valeurs pour la création de l'objet (ex: nom="John", email="example@example.com")
    :return: L'instance créée ou None en cas d'erreur.
    """
    try:
        obj = model.objects.create(**kwargs)
        logging.info(f"Nouvel objet {model.__name__} créé : {obj}")
        return obj
    except Exception as e:
        logging.error(f"Erreur lors de la création d'un {model.__name__} : {e}")
        return None


def update_object(model, filters, updates):
    """
    Met à jour un objet existant d'un modèle Django.
    :param model: Classe du modèle Django (ex: Agent, Demarche)
    :param filters: Critères pour identifier l'objet à mettre à jour (ex: {"email": "example@example.com"})
    :param updates: Champs et valeurs à mettre à jour (ex: {"nom": "Doe", "prenom": "Jane"})
    :return: L'instance mise à jour ou None si l'objet n'est pas trouvé.
    """
    try:
        obj = model.objects.get(**filters)
        updated_fields = []  # Liste pour suivre les champs modifiés

        for field, value in updates.items():
            setattr(obj, field, value)
            updated_fields.append(field)

        obj.save()
        logging.info(f"{model.__name__} mis à jour : {obj}. Champs modifiés : {', '.join(updated_fields)}")
        return obj
    
    except model.DoesNotExist:
        logging.warning(f"Aucun {model.__name__} trouvé avec les critères : {filters}")
        return None
    
    except Exception as e:
        logging.error(f"Erreur lors de la mise à jour d'un {model.__name__} : {e}")
        return None


def get_number_demarche_Postgres():
    """
        Récupère sur Postgres le numéro 'Démarches-Simplifiées' de nos démarches
    """

    # Récupérer toutes les démarches avec leur numéro
    demarches = Demarche.objects.all().values('numero', 'titre')

    list_number_demarches = []

    # Affichage dans la console
    for d in demarches:
        list_number_demarches.append(d['numero'])

    return list_number_demarches