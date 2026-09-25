import json
import logging
import os

from django.utils import timezone
from django.urls import reverse
from datetime import date, datetime, timedelta

import smbclient
from django.conf import settings

from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierManifSportiveDocument
from autorisations.models.models_instruction import DossierManifSportive, DossierManifestationLiaison
from autorisations.models.models_utilisateurs import DossierInstructeur, DossierManifSportiveInstructeur
from autorisations.utils.nas_fonctions import _normalize_unc_path, ecrire_file_sur_nas
from instruction.utils.document_utils import normaliser_emplacement
from notifications.service import compute_dedupe_key, create_EmailOutbox_DM, envoi_mail
from synchronisation.utils.conversion import parse_datetime_with_tz
from synchronisation.utils.model_helpers import update_fields

from .utils import formattage_geojson
from .get_methods import get_access_token, get_all_avis, get_dossier_by_id, get_file, get_geojson, get_pj_dossier

loggerDM = logging.getLogger("API_DM")
loggerSynchro = logging.getLogger("SYNCHRONISATION")
logger = logging.getLogger("ORM_DJANGO")


def date_demande_inferieure_un_an(avis):
    date_demande = avis.get("date_demande")
    if not date_demande:
        return False

    if isinstance(date_demande, str):
        val = datetime.fromisoformat(date_demande)
    else:
        val = date_demande

    # Si c’est un objet date simple (sans heure)
    if isinstance(val, date) and not isinstance(val, datetime):
        val = datetime.combine(val, datetime.min.time())

    # Rendre aware dans le fuseau local si nécessaire
    if timezone.is_naive(val):
        val = timezone.make_aware(val, timezone.get_current_timezone())

    return val >= timezone.now() - timedelta(days=365)



def parser_date_dm(val):
    """
    Convertit une valeur date/datetime/str en datetime aware.
    Retourne None si vide.
    """
    if not val:
        return None

    if isinstance(val, str):
        val = datetime.fromisoformat(val)

    if isinstance(val, date) and not isinstance(val, datetime):
        val = datetime.combine(val, datetime.min.time())

    if timezone.is_naive(val):
        val = timezone.make_aware(val, timezone.get_current_timezone())

    return val


def doit_traiter_dossier_dm(manif_id):
    """
    Retourne True si :
    - le dossier DM n'existe pas encore en base
    - ou s'il existe et que sa date de fin d'évènement est dans le futur
    - ou s'il existe et que sa date de fin d'évènement date de moins de 7 jours
    """
    dossier_bdd = DossierManifSportive.objects.filter(numero_dossier_declaration_manifestations=manif_id).first()

    # Nouveau dossier DM
    if not dossier_bdd:
        return True

    date_fin = parser_date_dm(dossier_bdd.date_fin_evenement)

    # Pas de date de fin : on choisit de continuer
    if not date_fin:
        return True

    maintenant = timezone.now()

    # Date fin dans le futur ou passée depuis moins de 7 jours
    if date_fin >= maintenant - timedelta(days=7):
        return True

    return False


def recup_avis_et_dossiers():
    """
    Récupère les avis et dossiers sur Déclaration Manifestations.
    """

    # Récupère le token
    token = get_access_token()

    # Récupération de tous les avis
    avis_list = get_all_avis(token)
    # [{ "id": int, "etat": "termine", "reponse_avis": "favorable", "service": "PN La Réunion (974)", "date_demande": date, "date_reponse": date, "manif_id": 106328, "objet_demande_str": null }, ...]

    loggerDM.info(f"{len(avis_list)} avis au total")
    loggerSynchro.info(f"{len(avis_list)} avis au total")

    # Détails pour chaque dossier
    dossiers = []
    unique_numeros = []


    ##############################################
    # FILTRE : Les demandes datant de moins d'un an
    ##############################################

    # numeros_dossiers_a_exclure = [88594, 87044, 114082, 107139, 118148, 117715, 113846, 121088, 122154]
    # 105963, 101156
    avis_filtres = [
        avis for avis in avis_list
        if (
            # avis.get("reponse_avis") is None
            # avis["manif_id"] not in numeros_dossiers_a_exclure
            # and avis.get("etat") not in ["termine", "caduc"]
            date_demande_inferieure_un_an(avis)  # demande date de - d'un an
            and doit_traiter_dossier_dm(avis["manif_id"]) # date de fin d'évènement est dans le futur ou date de moins de 7 jours
        )
    ]

    # FILTRE AVIS POUR LE DEV
    # avis_filtres = [ avis for avis in avis_list if ( avis.get("manif_id") in [108318] )]   
    # avis_filtres = [ avis for avis in avis_list if ( avis.get("manif_id") in [108034, 114426, 98151, 101156, 112748, 116432, 113846, 110346, 108237] )]   


    loggerDM.info(f"{len(avis_filtres)} avis récupéré(s) après filtre sur Déclaration manifestations")
    loggerSynchro.info(f"{len(avis_filtres)} avis récupéré(s) après filtre sur Déclaration manifestations")
    loggerDM.info(f"On récupère les dossiers en cours, de ces avis non rendus.")

    # ---------------------------------------------------
    # Récupération des dossiers et géojson associé sur DM
    # ---------------------------------------------------
    if avis_filtres :
        for avis in avis_filtres:

            manif_id = avis["manif_id"]

            dossier = get_dossier_by_id(token, manif_id)

            if dossier:
                if dossier["pk"] not in unique_numeros:

                    unique_numeros.append(dossier["pk"])
                    # On récupère le geojson
                    geojson = get_geojson(token, manif_id)

                    # Formattage du geojson
                    if geojson :
                        geojson = formattage_geojson(geojson)
                        dossier["geometrie"] = geojson
                    else :
                        loggerDM.error(f"Problème lors de la récupération du Geojson sur Déclaration Manifestations {dossier['nom']} ({dossier['pk']}) : Geojson vide")
                        dossier["geometrie"] = None

                    # Log si : date du jour > date de fin de la manif  ET  etat dossier != annulée
                    date_fin_evenement =  parse_datetime_with_tz(dossier.get("date_fin"))
                    etat_dossier = dossier.get("etat")
                    
                    # Si evenement a eu lieu il y a moins de 100 jours ET avis pas rendu
                    avis_rendu = True if avis['reponse_avis'] or avis['etat'] == "termine" else False
                    if (date_fin_evenement and date_fin_evenement < timezone.now() and (timezone.now() - date_fin_evenement) < timedelta(days=100) and not avis_rendu) :
                        nom_dossier = dossier.get("nom")
                        numero_dossier_declaration_manifestations = dossier.get("pk")

                        loggerSynchro.warning(f"Récupération infos sur DM : Dossier {numero_dossier_declaration_manifestations} " +
                            f"({nom_dossier}) n'a aucun avis rendu, or la manifestation est déjà passée ({date_fin_evenement})."
                        )

                    dossiers.append(dossier)

                else :
                    loggerDM.warning(f"Le dossier {dossier['nom']} ({dossier['pk']}) est en double sur Déclaration Manifestations")
    

    loggerDM.info(f"{len(dossiers)} dossier(s) récupéré(s) sur Déclaration manifestations")
    loggerSynchro.info(f"{len(dossiers)} dossier(s) récupéré(s) sur Déclaration manifestations")

    return dossiers, avis_filtres



def recup_un_seul_dossier(manif_id):
    """
    Récupère un dossier sur Déclaration Manifestations.
    """

    # Récupère le token
    token = get_access_token()

    dossier = get_dossier_by_id(token, manif_id)
    if dossier:
            
        loggerDM.info(f"Dossier {dossier.get('nom')} récupéré")

        # On récupère le geojson
        geojson = get_geojson(token, manif_id)

        # Formattage du geojson
        if geojson :
            geojson = formattage_geojson(geojson)
            dossier["geometrie"] = geojson
        else :
            loggerDM.error(f"Problème lors de la récupération du Geojson sur Déclaration Manifestations {dossier['nom']} ({dossier['pk']}) : Geojson vide")
            dossier["geometrie"] = None
        
    return [dossier]



def notifier_nouvelles_pj_dm_apres_avis(doss, nouvelles_pjs):
    """Notifie les instructeurs après récupération de PJ déposées après l'avis."""
    numero_dm = doss.numero_dossier_declaration_manifestations
    emails = set(
        DossierManifSportiveInstructeur.objects.filter(
            id_dossier_manif_sportive=doss,
            id_instructeur__email__isnull=False,
        ).exclude(
            id_instructeur__email="",
        ).values_list("id_instructeur__email", flat=True)
    )

    liaisons_dn = list(DossierManifestationLiaison.objects.filter(
        id_dossier_manif=doss,
    ).select_related("id_dossier__id_etape_dossier"))
    dossiers_dn_ids = [liaison.id_dossier_id for liaison in liaisons_dn]
    emails.update(
        DossierInstructeur.objects.filter(
            id_dossier_id__in=dossiers_dn_ids,
            id_instructeur__email__isnull=False,
        ).exclude(
            id_instructeur__email="",
        ).values_list("id_instructeur__email", flat=True)
    )
    emails = sorted({email.strip().lower() for email in emails if email and email.strip()})
    if not emails:
        loggerSynchro.warning(
            f"[DOSSIER DM {numero_dm}] Nouvelle(s) PJ récupérée(s) après avis rendu, "
            "mais aucun instructeur affecté à notifier."
        )
        return

    destinataires = emails if settings.NOTIFS_PROD else [settings.EMAIL_NOTIF_TEST]
    destinataires = [email for email in destinataires if email]
    if not destinataires:
        loggerSynchro.error(
            f"[DOSSIER DM {numero_dm}] Notification des nouvelles PJ impossible : aucun email destinataire configuré."
        )
        return

    sujet = f"Dossier DM {numero_dm} - Nouvelle pièce jointe après le rendu de l'avis"
    if len(nouvelles_pjs) > 1:
        sujet = f"Dossier DM {numero_dm} - Nouvelles pièces jointes après le rendu de l'avis"
    base_url = os.getenv("URL_APPLI", "").rstrip("/")
    dossier_url = (
        f"{base_url}/instruction/declaration_manifestations/{numero_dm}/"
    )
    if liaisons_dn:
        dossier_dn = liaisons_dn[0].id_dossier
        if dossier_dn.id_etape_dossier.etape == "À affecter":
            chemin_dossier = reverse(
                "preinstruction_dossier",
                kwargs={"numero": dossier_dn.numero},
            )
        else:
            chemin_dossier = reverse(
                "instruction_dossier",
                kwargs={"num_dossier": dossier_dn.numero},
            )
        dossier_url = f"{base_url}{chemin_dossier}"

    context = {
        "dossier_numero": numero_dm,
        "dossier_nom": doss.nom_dossier,
        "pieces_jointes": nouvelles_pjs,
        "url": dossier_url,
    }
    template_name = "nouvelles_pj_dm_apres_avis"
    dedupe = compute_dedupe_key(destinataires, sujet, template_name, context)
    outbox = create_EmailOutbox_DM(
        destinataires,
        sujet,
        template_name,
        dedupe,
        context,
        doss,
        type_mail="Notification",
        email_from=settings.DEFAULT_FROM_EMAIL,
    )
    if not outbox:
        loggerSynchro.error(f"[DOSSIER DM {numero_dm}] Échec de création de la notification des nouvelles PJ.")
        return

    ok, erreur = envoi_mail(outbox.id)
    if ok:
        loggerSynchro.info(
            f"[DOSSIER DM {numero_dm}] Notification de {len(nouvelles_pjs)} nouvelle(s) PJ envoyée à "
            f"{', '.join(destinataires)}."
        )
    else:
        loggerSynchro.error(
            f"[DOSSIER DM {numero_dm}] Échec de la notification des nouvelles PJ : {erreur}"
        )


def recup_pj_dossiers(doss, docs, token, doss_lie, token_prod, avis_deja_rendu=False):
    """
    doss = DossierManifSportive
    docs = [Document] du doss
    token = Token API Déclaration Manifestations
    doss_lie = True si Dossier DM lié à un dossier DN, False sinon
    token_prod = Token API PROD

    Récupération des Pj associées au dossier sur Déclaration Manifestations.
    Synchronisation NAS et BDD
    """

    manif_id = doss.numero_dossier_declaration_manifestations
    nas_root = os.environ.get("NAS_ROOT")
    if not nas_root:
        loggerSynchro.error(
            f"[DOSSIER DM {manif_id}] Synchronisation des PJ impossible : NAS_ROOT est vide."
        )
        return doss

    # Récupération des pjs
    liste_pj = get_pj_dossier(token, manif_id)

    # [{ "id": 950564, "document_attache": null, "historique": [], "date_modification_model": "2026-01-30T10:10:20.753457+01:00", 
    #    "nom": "Attestation de présence de médecin(s)", "champ_cerfa": "presence_docteur", "info": "", "validation_instructeur": false, "date_demande": null,
    #    "date_limite": null, "date_televersement": null, "scan_antivirus": true, "tentative_scan": 0, "document_attache_taille_maximum": 25,
    #    "history_json": null, "is_archived": false, "demande_par_utilisateur": null, "demande_par_service": null, "valide_par_service": null, "instance": null
    #  }, ... ]

    if not liste_pj:
        loggerDM.warning(f"[Dossier Déclaration Manifestations {manif_id} - {doss.nom_dossier}] Aucune PJ visible depuis l'API DM")
        return doss
    

    # Liste des ids des Document étant liés à un DossierManifSportive du doss
    docs_ids = {doc.id for doc in docs}


    compteur_nouvelles_pjs_recup = 0
    nouvelles_pjs = []

    for pj in liste_pj:
        url = pj.get("document_attache")

        # Un document est bien présent sur DM
        if url :
            
            # RÉCUPÉRATION DES INFOS
            titre = url.split('/')[-1]
            pj_dm_id = pj.get("id")
            format_fichier = url.split('.')[-1].lower()
            id_format = DocumentFormat.objects.filter(format=format_fichier).first()
            id_nature = DocumentNature.objects.filter(nature__iexact="Pièce jointe demandeur").first()

            if not id_format:
                loggerSynchro.error(f"[DOSSIER MANIF SPORTIVE {manif_id}] Format inconnu pour '{titre}' : {format_fichier}")
                continue

            if not id_nature:
                loggerSynchro.error(f"[DOSSIER MANIF SPORTIVE {manif_id}] Nature 'Pièce jointe demandeur' introuvable.")
                return doss


            description = pj.get("nom")
            date_televersement = parse_datetime_with_tz(pj.get("date_televersement"))
            
            # if doss_lie :
            #     emplacement_doc = os.path.join(doss.emplacement, "Annexes/Déclaration Manifestations/")
            # else :
            emplacement_doc = normaliser_emplacement(
                os.path.join(doss.emplacement, "Annexes")
            )
            emplacement_file = _normalize_unc_path(
                os.path.join(nas_root, emplacement_doc, titre)
            )


            fields_to_update = {
                "id_format": id_format,
                "id_nature": id_nature,
                "url_dm": url,
                "emplacement": normaliser_emplacement(emplacement_doc),  # important
                "description": description,
                "titre": titre,
                "date": date_televersement,
                "pj_dm_id": pj_dm_id,
            }

            defaults={
                "id_format": id_format,
                "id_nature": id_nature,
                "url_dm": url,
                "description": description,
                "date": date_televersement,
                "pj_dm_id": pj_dm_id,
            }


            # Le doc existe-t-il sur le NAS ?
            fichier_existe_sur_NAS = smbclient.path.exists(emplacement_file)

            # Le doc existe-t-il en BDD ?
            doc_bdd = None
            if pj_dm_id is not None:
                doc_bdd = Document.objects.filter(pj_dm_id=pj_dm_id).first()
            document_existe_en_bdd = doc_bdd is not None
            est_nouvelle_pj_ou_version = not document_existe_en_bdd or (
                date_televersement is not None
                and doc_bdd.date is not None
                and date_televersement > doc_bdd.date
            )


            # -----------------------------
            # DOCUMENT EXISTE DEJA EN BDD
            # -----------------------------
            if document_existe_en_bdd :

                # On s'assure qu'il y a bien une liaison DossierManifSportiveDocument
                if doc_bdd and doc_bdd.id not in docs_ids:
                    obj, created = DossierManifSportiveDocument.objects.get_or_create(id_dossier_manif_sportive=doss, id_document=doc_bdd)
                    docs_ids.add(doc_bdd.id)
                
                # ----------------------------
                # -- DOC PRÉSENT SUR LE NAS --
                # ----------------------------
                if fichier_existe_sur_NAS:
                        
                    if date_televersement is None or doc_bdd.date is None or date_televersement <= doc_bdd.date:
                        # Check MAJ Document

                        try:
                            updated_fields = update_fields(doc_bdd, fields_to_update, date_fields=["date"])
                            if updated_fields:


                                doc_bdd.save(update_fields=updated_fields)
                                loggerSynchro.info(f"[DOSSIER MANIF SPORTIVE {manif_id}] Document {doc_bdd} mis à jour. Changements: {', '.join(updated_fields)}")

                        except Exception as e:
                            loggerSynchro.error(f"[DOSSIER MANIF SPORTIVE {manif_id}] Synchro : Erreur lors de la mise à jour du Document {doc_bdd} : {e}")
                            continue
                        continue

                    # else :
                        # + bas : 
                        # écriture sur le NAS + MAJ Document

                # ---------------------------
                # -- DOC ABSENT SUR LE NAS --
                # ---------------------------
                if not fichier_existe_sur_NAS:
                    loggerSynchro.warning(
                        f"[DOSSIER DM {manif_id}] Incohérence PJ DM id={pj_dm_id} : Document {doc_bdd.id} présent en BDD "
                        f"mais absent sur le NAS à l'emplacement '{emplacement_file}'"
                    )
                    # + bas :
                    # MAJ Doc + écrire sur le NAS + bas

            
            # --------------------------
            # DOCUMENT ABSENT EN BDD
            # --------------------------
            else :
                # ----------------------------
                # -- DOC PRÉSENT SUR LE NAS --
                # ----------------------------
                if fichier_existe_sur_NAS:
                    loggerSynchro.warning(
                        f"[DOSSIER DM {manif_id}] Incohérence PJ DM id={pj_dm_id} : "
                        f"Document absent en BDD mais fichier présent sur le NAS à l'emplacement '{emplacement_file}'."
                    )

                    # Création ou mise à jour du Document (contrainte UNIQUE emplacement,titre)
                    doc, created = Document.objects.get_or_create(emplacement=emplacement_doc, titre=titre, defaults=defaults)

                    # On s'assure qu'il y a bien une liaison DossierManifSportiveDocument
                    if doc and doc.id not in docs_ids:
                        obj, created = DossierManifSportiveDocument.objects.get_or_create(id_dossier_manif_sportive=doss, id_document=doc)
                        docs_ids.add(doc.id)

                    if created:
                        loggerSynchro.warning(f"[CREATE] Document {doc} créé pour le Dossier Manif Sportive {manif_id}. Le fichier était lui, déjà présent sur le NAS.")
                    else:
    
                        try:
                            updated_fields = update_fields(doc, fields_to_update, date_fields=["date"])
                            if updated_fields:
                                doc.save(update_fields=updated_fields)
                                loggerSynchro.info(f"[DOSSIER MANIF SPORTIVE {manif_id}] Document {doc} mis à jour. Changements: {', '.join(updated_fields)}")

                        except Exception as e:
                            loggerSynchro.error(f"[DOSSIER MANIF SPORTIVE {manif_id}] Synchro : Erreur lors de la mise à jour du Document {doc} : {e}")
                            continue

                    if est_nouvelle_pj_ou_version:
                        nouvelles_pjs.append({
                            "pj_dm_id": pj_dm_id,
                            "titre": titre,
                            "description": description,
                            "date_televersement": (
                                date_televersement.isoformat()
                                if date_televersement else None
                            ),
                        })
                        compteur_nouvelles_pjs_recup += 1
                    continue
                
                # ---------------------------
                # -- DOC ABSENT SUR LE NAS --
                # ---------------------------
                # else :
                    # + bas :
                    # écrire sur le NAS + Création Document (attention aux contraintes)

            
            # -----------------------------------------
            # ÉCRITURE SUR LE NAS POUR LES NOUVELLES PJ
            # -----------------------------------------
            try :

                # Récupération du fichier sur DM
                file = get_file(token_prod, url)  #Bytes

            except Exception as e:
                loggerDM.warning(f"[DOSSIER MANIF SPORTIVE {manif_id} - {doss.nom_dossier}] Erreur lors du téléchargement de '{description}' ({url}) : {e}")
                continue
            

            # Ecriture sur le NAS (écrase fichier si existant)
            if not ecrire_file_sur_nas(file, emplacement_file) :
                loggerDM.error(f"[DOSSIER MANIF SPORTIVE {manif_id}] Échec de l’écriture du fichier {emplacement_file}")
                continue
            

            # DOC EXISTE EN BDD
            if document_existe_en_bdd :
                # MAJ DOCUMENT
                try:

                    updated_fields = update_fields(doc_bdd, fields_to_update, date_fields=["date"])
                    if updated_fields:
                        doc_bdd.save(update_fields=updated_fields)
                        loggerSynchro.info(f"[DOSSIER MANIF SPORTIVE {manif_id}] Document {doc_bdd} mis à jour. Changements: {', '.join(updated_fields)}")

                except Exception as e:
                    loggerSynchro.error(f"[DOSSIER MANIF SPORTIVE {manif_id}] Synchro : Erreur lors de la mise à jour du Document {doc_bdd} : {e}")
                    continue
            
            # DOCUMENT(pj_dm_id=pj_dm_id) : ABSENT EN BDD
            else : 
                # Création ou mise à jour du Document (contrainte UNIQUE emplacement,titre)
                doc, created = Document.objects.get_or_create(emplacement=emplacement_doc, titre=titre, defaults=defaults)

                # On s'assure qu'il y a bien une liaison DossierManifSportiveDocument
                if doc and doc.id not in docs_ids:
                    obj, created = DossierManifSportiveDocument.objects.get_or_create(id_dossier_manif_sportive=doss, id_document=doc)
                    docs_ids.add(doc.id)


                if created:
                    loggerSynchro.info(f"[CREATE] Document {doc} créé pour le Dossier Manif Sportive {manif_id}.")
                else:

                    try:
                        updated_fields = update_fields(doc, fields_to_update, date_fields=["date"])
                        if updated_fields:
                            doc.save(update_fields=updated_fields)
                            loggerSynchro.info(f"[DOSSIER MANIF SPORTIVE {manif_id}] Document {doc} mis à jour. Changements: {', '.join(updated_fields)}")

                    except Exception as e:
                        loggerSynchro.error(f"[DOSSIER MANIF SPORTIVE {manif_id}] Synchro : Erreur lors de la mise à jour du Document {doc} : {e}")
                        continue

            # COMPTEUR NOUVELLES PJ
            compteur_nouvelles_pjs_recup += 1
            if est_nouvelle_pj_ou_version:
                nouvelles_pjs.append({
                    "pj_dm_id": pj_dm_id,
                    "titre": titre,
                    "description": description,
                    "date_televersement": (
                        date_televersement.isoformat()
                        if date_televersement else None
                    ),
                })
    

    if compteur_nouvelles_pjs_recup > 0 :
        loggerDM.info("---")
        loggerDM.info(f"[Dossier {manif_id} - {doss.nom_dossier}] {compteur_nouvelles_pjs_recup} nouvelles PJ récupérées")

    # if avis_deja_rendu and nouvelles_pjs:
    #     try:
    #         notifier_nouvelles_pj_dm_apres_avis(doss, nouvelles_pjs)
    #     except Exception as e:
    #         # La PJ est déjà sauvegardée : une erreur de mail ne doit jamais
    #         # faire échouer la synchronisation du dossier.
    #         loggerSynchro.exception(
    #             f"[DOSSIER DM {manif_id}] Échec de la notification des nouvelles PJ après avis rendu : {e}"
    #         )

    return doss
