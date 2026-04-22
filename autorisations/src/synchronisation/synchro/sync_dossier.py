from autorisations.models.models_instruction import Demarche, Dossier, DossierManifSportive, DossierManifestationLiaison, EtapeDossier
from autorisations.models.models_utilisateurs import Instructeur
from instruction.utils_instru import enregistrer_action, template_mail_name_from_etape
from synchronisation.utils.instruction import lier_dossier_dm_au_dossier_dn
from ..utils.model_helpers import update_fields, foreign_keys_add_suffixe_id
from ..utils.fichiers import create_emplacement, write_geojson
from django.db import models
from datetime import date, datetime
import logging

logger = logging.getLogger('SYNCHRONISATION')

def sync_doss(dossier, dico_notifs, dossiers_champs=None):
    """
    Synchronise un objet Dossier à partir des données D-S.

    { "id_ds", "id_etat_dossier", "id_demarche", "numero", "id_groupeinstructeur", 
    "date_depot", "date_fin_instruction", "id_dossier_type", 
    "note", "nom_dossier", "emplacement", "date_limite_traitement", "geometrie", "present_sur_ds" }

    dossiers_champs = [{"nom_champ", "id_ds", "valeur", "date_saisie", "geometrie", "id_document"...}] : Utile pour lier un dossier DM à un dossier DN

    "id_dossier_type" est à nouveau par défaut
    """
    defaults = foreign_keys_add_suffixe_id(Dossier, dossier)

    obj, created = Dossier.objects.get_or_create(
        id_ds=dossier["id_ds"],
        numero=dossier["numero"],
        defaults=defaults
    )


    demarche = Demarche.objects.filter(id=dossier['id_demarche']).first()

    # ----------------------------
    # NOUVEAU Dossier DN
    # ----------------------------
    if created:
        logger.info(f"[CREATE] Dossier {obj.numero} (id_ds: {obj.id_ds}) créé.")

        # Création des folders
        create_emplacement(obj.emplacement)


        #-----------------------------------------------------
        #  Manifestations Sportives : DOSSIER DM EXISTANT ?
        #-----------------------------------------------------
        if demarche.type.lower() == 'manifestations sportives':

            try :
                manif_id = None
                for ch in dossiers_champs:
                    dossier_champ = ch["champ"]
                    if dossier_champ["nom_champ"] == 'Numéro du dossier sur la plateforme déclaration-manifestations' :
                        manif_id = int(dossier_champ["valeur"])
                        break
                    else :
                        continue
                

                # On vérifie si un Dossier Déclaration Manifestations (non archivé) existe
                dossier_dm = DossierManifSportive.objects.filter(numero_dossier_declaration_manifestations=manif_id, archive=False).first()
                
                # -------------------------------------------
                # Dossier Déclaration Manifestations existant
                # -------------------------------------------
                if dossier_dm :
                    # Création liaison : On déplace les fichiers, met à jour les emplacements
                    try :
                        lier_dossier_dm_au_dossier_dn(dossier_dm, obj, obj.emplacement, logger)
                    except Exception as e:
                        logger.error(f"Erreur lors de la création de la liaison Dossier DN {obj.numero} <=> Dossier DM {manif_id} (Incluant le transfert des fichiers du Dossier DM) : {e}")


                # ---------------------------------------------
                # Dossier Déclaration Manifestations inexistant
                # ---------------------------------------------
                else :
                    logger.warning(f"[CREATE Dossier Manif Sportive {obj.numero} - Démarche Numérique] Le Dossier Déclaration Manifestations {manif_id} n'a pas été trouvé. Peut être s'agit-il d'une erreur de saisie dans le formulaire DN.")
                
            except Exception as e:
                logger.error(f"[CREATE Dossier Manif Sportive {obj.numero} - Démarche Numérique] Échec de la création de la Liaison avec le Dossier DM {manif_id} : {e}")


        # Write geojson
        if obj.geometrie :
            write_geojson(f"{obj.emplacement}/Carto", f"{obj.numero}.geojson",obj.geometrie)

        instructeur = Instructeur.objects.first()

        try:
            demarche_obj = Demarche.objects.get(id=dossier['id_demarche'])
        except Demarche.DoesNotExist:
            logger.error(f"Dossier {obj.numero} : Aucune démarche trouvée avec l'id : {dossier['id_demarche']}")
        
        type_demarche = demarche_obj.type
        # Dossier Action 'Dossier reçu'
        enregistrer_action(obj, instructeur, "Dossier reçu", date=dossier['date_depot'], description=type_demarche)

        # Dossier en instruction
        if obj.id_etat_dossier.nom == "en_instruction":
            logger.warning(f"Dossier {obj.numero} : Le dossier est apparu en création alors qu'il est déjà 'en_instruction' sur DS. DossierEtape mis à 'En instruction' pour un soucis de cohérence.")
            etape_en_instruction = EtapeDossier.objects.get(etape='En instruction')
            obj.id_etape_dossier = etape_en_instruction
            obj.save()
        
        # Dossier accepté
        if obj.id_etat_dossier.nom == "accepte":
            logger.warning(f"Dossier {obj.numero} : Le dossier est apparu en création alors qu'il est déjà 'accepte' sur DS. DossierEtape mis à 'Accepté' pour un soucis de cohérence.")
            etape_accepte = EtapeDossier.objects.get(etape='Accepté')
            obj.id_etape_dossier = etape_accepte
            obj.save()

        # Dossier refusé     
        if obj.id_etat_dossier.nom == "refuse":
            logger.warning(f"Dossier {obj.numero} : Le dossier est apparu en création alors qu'il est déjà 'refuse' sur DS. DossierEtape mis à 'Refusé' pour un soucis de cohérence.")
            etape_refuse = EtapeDossier.objects.get(etape='Refusé')
            obj.id_etape_dossier = etape_refuse
            obj.save()

        # Dossier classé sans suite   
        if obj.id_etat_dossier.nom == "sans_suite":
            logger.warning(f"Dossier {obj.numero} : Le dossier est apparu en création alors qu'il est déjà 'sans_suite' sur DS. DossierEtape mis à 'Non soumis à autorisation' pour un soucis de cohérence.")
            etape_sans_suite = EtapeDossier.objects.get(etape='Non soumis à autorisation')
            obj.id_etape_dossier = etape_sans_suite
            obj.save()


        #######################
        # NOTIFICATION PAR MAIL 
        #######################
        # dem = template_mail_name_from_etape(type_demarche)
        if demarche.type.lower() == 'manifestations sportives':
            type_demarche = "Manifestations sportives (Démarche Numérique)"
        if type_demarche in dico_notifs:
            dico_notifs[type_demarche] += 1
        else:
            dico_notifs[type_demarche] = 1


    # ----------------------------
    # Dossier DN EXISTANT
    # ----------------------------
    else:
        update_data = {}

        for field, new_value in dossier.items():
            # On exclu l'id groupe instructeur (on ne veut pas surcharger le GI s'il a été changé sur l'appli) 
            # et l'emplacement (pour ne pas écrasé l'emplacement d'un dossier manif sportive qui aurait été recu sur Déclaration Manifestations en 1er)
            if field != "id_groupeinstructeur" and field != "emplacement" :
                model_field = getattr(obj.__class__, field, None)
                field_name = f"{field}_id" if isinstance(getattr(model_field, 'field', None), models.ForeignKey) else field
                update_data[field_name] = new_value if isinstance(new_value, (date, datetime)) else new_value

        updated_fields = update_fields(
            obj,
            update_data,
            date_fields=[k for k, v in dossier.items() if isinstance(v, (date, datetime))]
        )

        if updated_fields:
            obj.save()
            logger.info(f"[SAVE] Dossier {obj.numero} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
            if "geometrie" in updated_fields :
                # Write geojson
                write_geojson(f"{obj.emplacement}/Carto", f"{obj.numero}.geojson",obj.geometrie)
        # else:
        #     logger.info(f"[NO CHANGE] Dossier {obj.numero} inchangé.")

    return obj.id
