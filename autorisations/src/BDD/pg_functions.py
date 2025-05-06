import logging
import django
import os
from django.db import connection
import requests
from typing import List, Type, Tuple, Optional

from autorisations.models.models_instruction import Demarche
from autorisations.models.models_instruction import Message
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, MessageDocument
from django.utils import timezone


logger = logging.getLogger('ORM_DJANGO')


def get_object(model, **kwargs):
    """
    Récupère un objet d’un modèle Django selon des critères donnés.

    Args:
        model (Model): La classe du modèle Django (ex. Agent, Dossier).
        **kwargs: Les critères de recherche (ex. id=5, email="x@x.com").

    Returns:
        instance or None: L’instance du modèle correspondant, ou None si non trouvée ou en cas d’erreur.
    """
    try:
        obj = model.objects.get(**kwargs)
        return obj

    except model.DoesNotExist:
        logging.warning(f"[GET] Aucun {model.__name__} trouvé avec les critères : {kwargs}")
        return None

    except Exception as e:
        logging.error(f"[GET] Erreur lors de la récupération d’un {model.__name__} avec {kwargs} : {e}")
        return None


def get_or_create_object(
        model: Type,
        search_kwargs: dict,
        defaults_kwargs: Optional[dict] = None,
        raise_exception: bool = False
    ) -> Tuple[object, bool]:
    """
    Récupère ou crée un objet d’un modèle Django selon les critères donnés.

    Args:
        model (Type): Classe du modèle Django (ex : Demarche, Agent).
        search_kwargs (dict): Champs utilisés pour rechercher l'objet (ex : {"numero": "DEM-123"}).
        defaults_kwargs (Optional[dict]): Champs utilisés si l'objet doit être créé (ex : {"libelle": "Nouvelle Démarche"}).
        raise_exception (bool): Si True, relance l'exception levée par Django au lieu de la logguer.

    Returns:
        Tuple[Optional[object], bool]: 
            - objet : L'instance récupérée ou créée (ou None en cas d’erreur si raise_exception=False)
            - created : True si l’objet a été créé, False s’il existait déjà.
    """

    try:
        obj, created = model.objects.get_or_create(
            **search_kwargs,
            defaults=defaults_kwargs or {}
        )
        logger.info(f"[GET_OR_CREATE] {model.__name__} {'créé' if created else 'trouvé'} avec {search_kwargs}")
        return obj, created

    except Exception as e:
        logger.error(f"[GET_OR_CREATE] Erreur sur {model.__name__} avec {search_kwargs} : {e}")
        if raise_exception:
            raise
        return None, False


def get_all_objects(model: Type) -> List[object]:
    """
    Récupère tous les objets d’un modèle Django donné.

    Args:
        model (Type): Classe du modèle Django (ex. : Agent, Demarche).

    Returns:
        List[object]: Liste des instances du modèle. Retourne une liste vide en cas d’erreur.
    """
    try:
        objs = list(model.objects.all())
        logger.info(f"[GET_ALL] {len(objs)} {model.__name__}(s) récupéré(s).")
        return objs

    except Exception as e:
        logger.error(f"[GET_ALL] Erreur lors de la récupération des {model.__name__}(s) : {e}")
        return []


def delete_object(model: Type, **kwargs) -> bool:
    """
    Supprime un objet d'un modèle Django selon les critères donnés.

    Args:
        model (Type): Classe du modèle Django (ex: Agent, Demarche).
        **kwargs: Critères de recherche (ex: id=1, email="example@example.com").

    Returns:
        bool: True si l'objet a été supprimé, False sinon.
    """
    try:
        obj = model.objects.get(**kwargs)
        obj.delete()
        logger.info(f"[DELETE] {model.__name__} supprimé avec les critères : {kwargs}")
        return True

    except model.DoesNotExist:
        logger.warning(f"[DELETE] Aucun {model.__name__} trouvé avec les critères : {kwargs}")
        return False

    except Exception as e:
        logger.error(f"[DELETE] Erreur lors de la suppression d’un {model.__name__} avec {kwargs} : {e}")
        return False


def delete_all_objects(model: Type) -> int:
    """
    Supprime tous les objets d’un modèle Django.

    Args:
        model (Type): Classe du modèle Django (ex : Agent, Demarche).

    Returns:
        int: Le nombre d’objets supprimés. Retourne 0 en cas d’erreur.
    """
    try:
        count, _ = model.objects.all().delete()
        logger.info(f"[DELETE_ALL] {count} objet(s) {model.__name__} supprimé(s).")
        return count
    except Exception as e:
        logger.error(f"[DELETE_ALL] Erreur lors de la suppression des {model.__name__} : {e}")
        return 0
    

def create_object(model: Type, **kwargs) -> Optional[object]:
    """
    Crée un nouvel objet pour un modèle Django.

    Args:
        model (Type): Classe du modèle Django (ex: Agent, Demarche).
        **kwargs: Champs et valeurs pour la création de l'objet (ex: nom="John", email="example@example.com").

    Returns:
        Optional[object]: L’instance créée, ou None en cas d’erreur.
    """
    try:
        obj = model.objects.create(**kwargs)
        logger.info(f"[CREATE] {model.__name__} créé : {obj}")
        return obj
    except Exception as e:
        logger.error(f"[CREATE] Erreur lors de la création d’un {model.__name__} avec {kwargs} : {e}")
        return None
    

def update_object(model: Type, filters: dict, updates: dict) -> Optional[object]:
    """
    Met à jour un objet existant d’un modèle Django selon des critères donnés.

    Args:
        model (Type): Classe du modèle Django (ex: Agent, Demarche).
        filters (dict): Critères d'identification de l’objet (ex: {"email": "example@example.com"}).
        updates (dict): Champs à mettre à jour et leurs nouvelles valeurs (ex: {"nom": "Doe"}).

    Returns:
        Optional[object]: L’instance mise à jour, ou None si l’objet n’a pas été trouvé ou en cas d’erreur.
    """
    try:
        obj = model.objects.get(**filters)
        updated_fields = []

        if not updates:
            logger.info(f"[UPDATE] Aucun champ à mettre à jour pour {model.__name__} avec {filters}")
            return obj

        for field, value in updates.items():
            setattr(obj, field, value)
            updated_fields.append(field)

        obj.save(update_fields=updated_fields)
        logger.info(f"[UPDATE] {model.__name__} mis à jour ({', '.join(updated_fields)}) : {obj}")
        return obj

    except model.DoesNotExist:
        logger.warning(f"[UPDATE] Aucun {model.__name__} trouvé avec les critères : {filters}")
        return None

    except Exception as e:
        logger.error(f"[UPDATE] Erreur lors de la mise à jour d’un {model.__name__} avec {filters} : {e}")
        return None


def get_number_demarche_Postgres():
    """
    Récupère tous les numéros des démarches enregistrées dans Postgres
    (liées à Démarches-Simplifiées via le champ `numero`).

    Returns:
        list[str]: Liste des numéros de démarches DS présents en base.
    """
    try:
        # Récupère uniquement les champs nécessaires
        numeros = Demarche.objects.values_list("numero", flat=True)
        return list(numeros)
    except Exception as e:
        import logging
        logging.error(f"[GET] Erreur lors de la récupération des numéros de démarches : {e}")
        return []



def create_message_bdd(
    body, email_emetteur, dossier_obj, 
    date_envoi=None, 
    document_file=None,  # fichier ouvert, ou None
    document_title=None,  # titre affiché (nom d'origine)
    document_format_str=None,  # ex: 'pdf', 'jpg'
    document_nature_str="Pièce jointe message",  # à adapter à ta nomenclature
    document_description=None,
    id_ds=None,
    url_ds=None
):
    """
    Crée un message en base (Postgres) et la pièce jointe si présente.

    Retourne : (message_obj, document_obj ou None)
    """

    try:

        # 1. Création du message (sans pièce jointe pour l'instant)
        msg = Message.objects.create(
            body=body,
            date_envoi=date_envoi or timezone.now(),
            piece_jointe=bool(document_file),
            email_emetteur=email_emetteur,
            id_dossier=dossier_obj,
            lu=False,
            id_ds=id_ds
        )

        logger.info(f"Message {id_ds} enregistré en BDD (dossier {dossier_obj.numero}) par {email_emetteur}")

        doc = None
        if document_file:

            try:

                # 2. Créer le Document
                # Récupérer ou créer le format et la nature
                doc_format, _ = DocumentFormat.objects.get_or_create(format=document_format_str)
                doc_nature, _ = DocumentNature.objects.get_or_create(nature=document_nature_str)

                # Définir le chemin de destination
                repertoire_annexes = os.path.join(os.environ.get("ROOT_FOLDER"), dossier_obj.emplacement, "Annexes")
                emplacement = os.path.join(repertoire_annexes, document_title)

                # Créer le répertoire si besoin
                os.makedirs(repertoire_annexes, exist_ok=True)

                with open(emplacement, 'wb+') as dest:
                    for chunk in document_file.chunks():
                        dest.write(chunk)

                doc = Document.objects.create(
                    id_format=doc_format,
                    id_nature=doc_nature,
                    emplacement=emplacement,
                    titre=document_title,
                    description=document_description or "",
                    url_ds=url_ds,
                )

                logger.info(f"Document {doc.id} enregistré à {emplacement}")

                # 3. Créer le lien message-document
                MessageDocument.objects.create(
                    id_message=msg,
                    id_document=doc
                )
                logger.info(f"Lien Message {msg.id} ↔ Document {doc.id} créé")

            except Exception as e_doc:
                logger.error(f"[BDD] Erreur lors de la création de la pièce jointe pour Message {msg.id} : {e_doc}")
                msg.delete()  # rollback du message si le document échoue
                raise Exception(f"Erreur lors de la création du document : {e_doc}")

        return msg, doc
    

    except Exception as e:
        logger.exception(f"Échec création message pour dossier {dossier_obj.numero}")
        raise  # pour remonter l'erreur plus haut si besoin
