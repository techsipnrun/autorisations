
from datetime import timedelta
import logging
import os

from django.db import transaction
import smbclient
from autorisations.models.models_documents import Document
from autorisations.models.models_instruction import DemandeType, Demarche, Dossier, DossierManifSportive, DossierManifestationLiaison, Priorite
from django.utils.timezone import now, is_naive, get_current_timezone, make_aware
from autorisations.utils.nas_fonctions import copier_dossier_smb, creer_dossier_sur_nas, supprimer_dossier_smb_recursif
from synchronisation.utils.conversion import parse_datetime_with_tz


loggerApp = logging.getLogger("APP")
loggerORM = logging.getLogger("ORM_DJANGO")
loggerSynchro = logging.getLogger("SYNCHRONISATION")


def calcul_priorite_instruction(id_demarche, doss):
    """
    Calcule la priorité d’instruction d’un dossier.

    Si le dossier est déjà traité (accepte/refuse/sans_suite) → priorité "traite".
    Sinon, compare la date limite à la date actuelle pour déterminer un niveau
    (urgent, normal, faible) en fonction du ratio de temps restant.

    Args:
        id_demarche (int): ID de la démarche liée au dossier.
        doss (dict): Données du dossier, incluant "dateDepot" et "state".

    Returns:
        Optional[int]: ID de la priorité, ou None en cas d’erreur.
    """
    if doss["state"] == "accepte" or doss["state"] == "refuse" or doss["state"] == "sans_suite" :
        return Priorite.objects.filter(niveau="traite").values_list("id", flat=True).first()
    
    else :
        date_depot_dossier = doss["dateDepot"]

        if id_demarche != 3 :  
            delais_jours_instruction = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()

        else :  # pour les travaux soumis à urbanisme le temps d'instruction max n'est pas le meme (selon  Permis Construire ou Déclaration Préalable)
            # si DP : 45 jours
            # sinon 120 jours (valeur de la colonne delais_jours_instruction)
            delais_jours_instruction = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()
    
        if not date_depot_dossier :
            loggerORM.error(f"[DOSSIER {doss['number']}] Erreur lors du calcul de Priorité d'instruction du dossier : la date de dépot du dossier est null")
            return None

        if delais_jours_instruction is None :
            loggerORM.error(f"[DOSSIER {doss['number']}] Erreur lors du calcul de Priorité d'instruction du dossier : la colonne delais_jours_instruction de la Démarche " +
                   f"{Demarche.objects.filter(id=id_demarche).values_list('type', flat=True).first()} est null")
            return None

        # Conversion de la date ISO 8601 en datetime Python
        try:
            date_depot = parse_datetime_with_tz(date_depot_dossier)
        except ValueError:
            return None  # ou logguer une erreur

        date_limite = date_depot + timedelta(days=delais_jours_instruction)
        today = now()

        if is_naive(today):
            today = make_aware(today, get_current_timezone())


        # Calcul du ratio restant
        jours_restants = (date_limite - today).total_seconds() / (3600 * 24)
        ratio_restant = jours_restants / delais_jours_instruction

        if ratio_restant < 0.3:
            niveau = "urgent"
        elif ratio_restant < 0.8:
            niveau = "normal"
        else:
            niveau = "faible"

        return Priorite.objects.filter(niveau=niveau).values_list("id", flat=True).first()
    


def calcul_date_limite_instruction(date_depot_iso: str, id_demarche: int):
    """
    Calcule la date limite théorique d’instruction en fonction de la date de dépôt
    et du délai prévu par la démarche.

    Args:
        date_depot_iso (str): Date ISO de dépôt.
        id_demarche (int): Identifiant de la démarche.

    Returns:
        Optional[datetime]: Date limite calculée ou None en cas d’erreur.
    """
    if not date_depot_iso:
        return None
    try:
        date_depot = parse_datetime_with_tz(date_depot_iso)
        delais = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()

        if delais is not None:
            return date_depot + timedelta(days=delais)
        
    except Exception as e:
        loggerApp.error(f"Erreur lors du calcul de la date_limite_instruction: {e}")
    return None



def calcul_priorite_instruction(id_demarche, doss):
    """
    Calcule la priorité d’instruction d’un dossier.

    Si le dossier est déjà traité (accepte/refuse/sans_suite) → priorité "traite".
    Sinon, compare la date limite à la date actuelle pour déterminer un niveau
    (urgent, normal, faible) en fonction du ratio de temps restant.

    Args:
        id_demarche (int): ID de la démarche liée au dossier.
        doss (dict): Données du dossier, incluant "dateDepot" et "state".

    Returns:
        Optional[int]: ID de la priorité, ou None en cas d’erreur.
    """

    # Cas 1 : Dossier déjà terminé
    if doss["state"] in ["accepte", "refuse", "sans_suite"]:
        return Priorite.objects.filter(niveau="traite").values_list("id", flat=True).first()

    # Cas 2 : Dossier en cours → on récupère la date de dépôt et le délai autorisé
    date_depot_dossier = doss["dateDepot"]
    delais_jours = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()

    if not date_depot_dossier:
        loggerORM.warning(f"[PRIORITE] Dossier sans date de dépôt (ID démarche : {id_demarche})")
        return None

    if delais_jours is None:
        description = Demarche.objects.filter(id=id_demarche).values_list("description", flat=True).first()
        loggerORM.warning(f"[PRIORITE] Délai d'instruction manquant pour la démarche : {description}")
        return None

    try:
        date_depot = parse_datetime_with_tz(date_depot_dossier)
    except ValueError:
        loggerApp.warning(f"[PRIORITE] Erreur de parsing date : {date_depot_dossier}")
        return None

    date_limite = date_depot + timedelta(days=delais_jours)
    today = now()

    if is_naive(today):
        today = make_aware(today, get_current_timezone())

    jours_restants = (date_limite - today).total_seconds() / (3600 * 24)
    ratio = jours_restants / delais_jours

    if ratio < 0.3:
        niveau = "urgent"
    elif ratio < 0.8:
        niveau = "normal"
    else:
        niveau = "faible"

    return Priorite.objects.filter(niveau=niveau).values_list("id", flat=True).first()



def calcul_date_limite_instruction(date_depot_iso: str, id_demarche: int):
    """
    Calcule la date limite théorique d’instruction en fonction de la date de dépôt
    et du délai prévu par la démarche.

    Args:
        date_depot_iso (str): Date ISO de dépôt.
        id_demarche (int): Identifiant de la démarche.

    Returns:
        Optional[datetime]: Date limite calculée ou None en cas d’erreur.
    """
    if not date_depot_iso:
        return None
    try:
        date_depot = parse_datetime_with_tz(date_depot_iso)
        delais = Demarche.objects.filter(id=id_demarche).values_list("delais_jours_instruction", flat=True).first()
        if delais is not None:
            return date_depot + timedelta(days=delais)
    except Exception as e:
        loggerApp.warning(f"[DELAIS] Erreur dans le calcul de la date limite : {e}")
    return None



def type_demande_from_nom_demarche(nom_demarche: str, champs: list):
    """
    Déduit le type de demande (DemandeType) à partir du nom d’une démarche.

    Args:
        nom_demarche (str): Nom complet de la démarche.
        champs (list(dict)) : Liste des champs du dossier  [{label: '', stringValue:''}, ...]

    Returns:
        Optional[int]: ID du DemandeType, ou 999 pour cas particulier, ou None si non reconnu.
    """
    correspondances = {
        "Activités commerciales": "Activités commerciales",
        "Travaux": "Travaux",
        "Mission scientifique": "Missions scientifiques",
        "hélicoptère": "Survol hélicoptère",
        "arêtes": "Arêtes",
        "Activités agricoles": "Activités agricoles",
        "Documents de planification et d'urbanisme": "Documents de planification et d'urbanisme",
        "Manifestations publiques": "Manifestations publiques",
        "Manifestations sportives": "Manifestations sportives",
        "Types Champ": "Test"
    }

    for mot_clef, type_ in correspondances.items():
        if mot_clef in nom_demarche:
            return DemandeType.objects.filter(type=type_).values_list("id", flat=True).first()

    if "Prise de vue et de son" in nom_demarche:
        return 999

    loggerApp.error(f"[TYPE DEMANDE] Nom non reconnu : {nom_demarche}")
    return None





def lier_dossier_dm_au_dossier_dn(dossier_dm, dossier_dn, emplacement, logger_arg):
    """
    Crée une liaison DossierManifSportive <=> Dossier,
    Déplace les documents du dossier DM vers l'emplacement DN,
    Met à jour les emplacements des Documents en base,
    Aligne l'emplacement du dossier DM sur celui du dossier DN.

    Args:
        dossier_dm: instance DossierManifSportive
        dossier_dn: instance Dossier
        emplacement (str): nouvel emplacement cible (celui du dossier DN)

    Returns: True si OK, False si Erreur
    """

    docs_deplaces = 0

    try:
        with transaction.atomic():
            # Verrouille les lignes si besoin de robustesse en concurrence
            dossier_dn = Dossier.objects.select_for_update().get(pk=dossier_dn.pk)
            dossier_dm = DossierManifSportive.objects.select_for_update().get(pk=dossier_dm.pk)

            num_DM = dossier_dm.numero_dossier_declaration_manifestations
            num_DN = dossier_dn.numero


            # Vérification si des liaisons existent
            liaison_existe_dossDM = DossierManifestationLiaison.objects.filter(id_dossier_manif=dossier_dm).exists()
            liaison_existe_dossDN = DossierManifestationLiaison.objects.filter(id_dossier=dossier_dn).exists()
            

            if liaison_existe_dossDM :
                logger_arg.warning(f"Échec de la création de la Liaison Dossier DM {num_DM} <=> Dossier DN {num_DN} ({dossier_dm.nom_dossier}). Le Dossier DM est déjà lié à un autre dossier DN.")
                return False
            
            elif liaison_existe_dossDN :
                logger_arg.warning(f"Échec de la création de la Liaison Dossier DM {num_DM} <=> Dossier DN {num_DN} ({dossier_dm.nom_dossier}). Le Dossier DN est déjà lié à un autre dossier DN.")
                return False
            
            else :
                liaison = DossierManifestationLiaison.objects.create(id_dossier_manif=dossier_dm, id_dossier=dossier_dn)
                logger_arg.info(f"[CREATE LIAISON] Dossier DM {num_DM} <=> Dossier DN {num_DN} ({dossier_dm.nom_dossier})")
                # Nom + parlant = Nom de la manif
                dossier_dn.nom_dossier_plus_parlant = dossier_dm.nom_dossier
                dossier_dn.save()


            # ----------------------------------------------------
            # Récupération des documents liés au dossier DM
            # ----------------------------------------------------
            docs_dm = Document.objects.filter(dossiermanifsportivedocument__id_dossier_manif_sportive=dossier_dm)
            
            root_folder = os.environ.get("NAS_ROOT")
            ancien_emplacement_dm = dossier_dm.emplacement
            ancien_emplacement_full_path = os.path.join(root_folder, ancien_emplacement_dm)
            nouvel_emplacement = emplacement
            nouvel_emplacement_full_path = os.path.join(root_folder, nouvel_emplacement)

            # SI Doss DM était dans le dossier "0 - En attente d'un dossier Démarche Numérique" : on peut le supprimer après son transfert
            supprimer_ancien_dossier = "En attente" in ancien_emplacement_dm

            # Crée le dossier cible si besoin
            creer_dossier_sur_nas(os.path.join(nouvel_emplacement_full_path, "Annexes", "Declaration Manifestations"))


            # -----------------------------------
            # On déplace les docs du Dossier DM
            # -----------------------------------
            for doc in docs_dm :

                if not doc.emplacement:
                    logger_arg.warning(f"[LIAISON DM/DN] Document {doc.id} ({doc.titre}) ignoré : emplacement vide en BDD.")
                    continue

                ancien_emplacement_doc_full_path = os.path.join(root_folder, doc.emplacement, doc.titre)
                nouvel_emplacement_doc = os.path.join(nouvel_emplacement, "Annexes", "Declaration Manifestations")
                nouvel_emplacement_doc_full_path = os.path.join(root_folder, nouvel_emplacement_doc, doc.titre)


                # SI LE FICHIER SOURCE N'EXISTE PAS
                if not smbclient.path.exists(ancien_emplacement_doc_full_path):
                    logger_arg.warning(f"[LIAISON DM/DN] Déplacements des fichiers DM : Fichier introuvable pour le document {doc.id} ({doc.titre}) : {ancien_emplacement_doc_full_path}")
                    continue


                # SI LE FICHIER CIBLE EXISTE DEJA
                if smbclient.path.exists(nouvel_emplacement_doc_full_path):
                    logger_arg.warning(f"[LIAISON DM/DN] Déplacements des fichiers DM : Le fichier cible existe déjà pour le document {doc.id} ({doc.titre}) : {nouvel_emplacement_doc_full_path}")

                    # Et on met à jour l'emplacement en base seulement si besoin
                    if doc.emplacement != nouvel_emplacement_doc:
                        doc.emplacement = nouvel_emplacement_doc
                        doc.save(update_fields=["emplacement"])

                    continue

                # Déplacement physique sur le NAS
                smbclient.rename(ancien_emplacement_doc_full_path, nouvel_emplacement_doc_full_path)

                # logger_arg.info(f"[LIAISON DM/DN] Document {doc.id} ({doc.titre}) déplacé : {ancien_emplacement_doc_full_path} -> {nouvel_emplacement_doc_full_path}")

                # MAJ emplacement document en base
                doc.emplacement = nouvel_emplacement_doc
                doc.save(update_fields=["emplacement"])

                docs_deplaces += 1

            logger_arg.info(f"[LIAISON DM/DN] {docs_deplaces} fichiers déplacés -> {nouvel_emplacement}")
        

            # ----------------------------
            # On déplace le fichier carto
            # ----------------------------
            carto_ancien_emplacement_full_path = os.path.join(ancien_emplacement_full_path, "Carto")
            carto_nouvel_emplacement_full_path = os.path.join(nouvel_emplacement_full_path, "Carto")

            if carto_ancien_emplacement_full_path != carto_nouvel_emplacement_full_path :
                try :
                    copier_dossier_smb(carto_ancien_emplacement_full_path,carto_nouvel_emplacement_full_path, logger_arg)
                except Exception as e :
                    msg = str(e)

                    if "being used by another process" in msg:
                        logger_arg.warning(f"[COPIE CARTO] Dossier DM {num_DM} <=> Dossier DN {num_DN} : "
                            f"fichier GeoJSON non supprimé car verrouillé par un autre processus "
                            f"(source={carto_ancien_emplacement_full_path}, cible={carto_nouvel_emplacement_full_path})"
                        )

                    else :
                        logger_arg.error(f"[COPIE DU FICHIER CARTO] Dossier DM {num_DM} <=> Dossier DN {num_DN} : Echec de l'écriture du fichier geojson "
                            f"(source={carto_ancien_emplacement_full_path}, cible={carto_nouvel_emplacement_full_path}) : {e}"
                        )

            # -------------------------------------------------
            # Si ancien dossier dans "0 - En attente d'un dossier Démarche Numérique", on le supprime
            # -------------------------------------------------
            if supprimer_ancien_dossier:
                try:
                    supprimer_dossier_smb_recursif(ancien_emplacement_full_path, logger_arg)
                    logger_arg.info(f"[SUPPRESSION DOSSIER SOURCE] Dossier DM {num_DM} : ancien dossier supprimé : {ancien_emplacement_dm}")
                except Exception as e:
                    logger_arg.warning(f"[SUPPRESSION DOSSIER SOURCE] Dossier DM {num_DM} : impossible de supprimer l'ancien dossier {ancien_emplacement_dm} : {e}")


            # ---------------------------------
            # MAJ Emplacement Dossier DM en BDD
            # ---------------------------------
            dossier_dm.emplacement = nouvel_emplacement
            dossier_dm.save(update_fields=["emplacement"])

            logger_arg.info(f"[LIAISON DM/DN] Emplacement du dossier DM {num_DM} mis à jour -> {nouvel_emplacement}")

            
            return True

    except Exception as e:
        logger_arg.exception(f"[LIAISON DM/DN] Erreur lors de la liaison du dossier DM {getattr(dossier_dm, 'pk', '?')} avec le dossier DN {getattr(dossier_dn, 'pk', '?')} : {e}")
        return False