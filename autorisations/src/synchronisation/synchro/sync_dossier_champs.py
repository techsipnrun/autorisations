import json
import os
from autorisations.models.models_instruction import Dossier, DossierChamp, Champ, ChampType, DossierManifSportive, DossierManifestationLiaison, DossierAction
from autorisations.models.models_documents import Document
from autorisations.models.models_utilisateurs import DossierInstructeur, Instructeur
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from ..utils.model_helpers import get_first_id, update_fields, update_fields_dossier_champs
from ..utils.date_activite import extraire_date_debut_activite, parser_date_activite
from ..utils.fichiers import rendre_titre_unique_dans_liste, write_pj, rendre_titres_uniques, write_pj_volumineuse
from ..utils.conversion import parse_datetime_with_tz
import logging
from django.utils import timezone
from autorisations.settings import EMAIL_NOTIF_TEST, NOTIFS_PROD
from instruction.utils.dossier_utils import safe_enregistrer_action

logger = logging.getLogger("SYNCHRONISATION")
loggerMail = logging.getLogger("MAIL")


def date_premiere_detection_pj(dossier, date_champ, premier_import):
    """Les PJ du premier import constituent une référence, sans historique supposé."""
    date = parse_datetime_with_tz(date_champ) or timezone.now()
    depot = parse_datetime_with_tz(getattr(dossier, "date_depot", None))
    if premier_import and depot:
        return min(date, depot)
    return date


def notifier_formulaire_modifie(dossier, champs_modifies, date_modification):
    """Un mail pour les champs distincts d'une même synchronisation du dossier."""
    try:
        if NOTIFS_PROD:
            emails = DossierInstructeur.objects.filter(id_dossier=dossier).values_list(
                "id_instructeur__email", flat=True,
            )
        else:
            emails = [EMAIL_NOTIF_TEST]
        destinataires = sorted({email.strip().lower() for email in emails if email and email.strip()})
        if not destinataires:
            loggerMail.warning(
                "[DOSSIER %s - FORMULAIRE MODIFIÉ] Notification non envoyée : aucun destinataire %s.",
                dossier.numero, "instructeur" if NOTIFS_PROD else "de test configuré",
            )
            return

        nombre_champs = len(champs_modifies)
        pluriel = "s" if nombre_champs > 1 else ""
        sujet = (
            f"Dossier n° {dossier.numero} - {dossier.id_demarche.type} : "
            f"{nombre_champs} champ{pluriel} ajouté{pluriel} ou modifié{pluriel} "
            "suite à une demande de compléments"
        )
        context = {
            "dossier_numero": dossier.numero,
            "demarche_type": dossier.id_demarche.type,
            "nombre_champs": nombre_champs,
            "url": f"{os.getenv('URL_APPLI', '').rstrip('/')}/instruction/{dossier.numero}/",
            # Distinguer deux modifications successives avec le même nombre de champs.
            "date_modification": date_modification.isoformat(),
            "champs_modifies": sorted(champs_modifies),
        }
        template_name = "dossier_modifie"
        dedupe = compute_dedupe_key(destinataires, sujet, template_name, context)
        outbox = create_EmailOutbox(
            destinataires, sujet, template_name, dedupe, context, dossier,
            type_mail="Notification",
        )
        if not outbox:
            loggerMail.error(
                "[DOSSIER %s - FORMULAIRE MODIFIÉ] Échec de création de la notification (%s champs).",
                dossier.numero, nombre_champs,
            )
            return

        ok, erreur = envoi_mail(outbox.id)
        if ok:
            loggerMail.info(
                "[DOSSIER %s - FORMULAIRE MODIFIÉ] Notification Email %s envoyée à %s (%s champs).",
                dossier.numero, outbox.id, ", ".join(destinataires), nombre_champs,
            )
        else:
            loggerMail.error(
                "[DOSSIER %s - FORMULAIRE MODIFIÉ] Échec d'envoi Email %s : %s.",
                dossier.numero, outbox.id, erreur,
            )
    except Exception:
        loggerMail.exception(
            "[DOSSIER %s - FORMULAIRE MODIFIÉ] Échec de notification ; la synchronisation continue.",
            dossier.numero,
        )


def sync_dossier_champs(dossier_champs, id_dossier, date_activite_champs=None):
    """
    Synchronise les DossierChamps avec ou sans pièce(s) jointe(s).
    """
    dossier = Dossier.objects.get(id=id_dossier)
    # Un seul contrôle au début : le premier import ne permet pas de déterminer
    # lesquelles des PJ étaient présentes lors du dépôt.
    premier_import = not DossierChamp.objects.filter(id_dossier_id=id_dossier).exists()
    ordre_number = 0
    date_modification_formulaire = None
    champs_modifies_formulaire = set()
    jour_derniere_demande_complements = None
    if getattr(getattr(dossier, "id_etape_dossier", None), "etape", None) == "En attente de compléments":
        # Une seule requête par dossier, jamais par champ. Comparaison par jour à La Réunion.
        date_demande = DossierAction.objects.filter(
            id_dossier_id=id_dossier, id_action__action="Demande de compléments",
        ).order_by("-date", "-id").values_list("date", flat=True).first()
        if date_demande:
            jour_derniere_demande_complements = parse_datetime_with_tz(date_demande).date()
        else:
            logger.warning(
                "[DOSSIER %s - FORMULAIRE MODIFIÉ] Notifications et action désactivées : "
                "aucune demande de compléments retrouvée dans l'historique.",
                dossier.numero,
            )
    pj_en_erreur = []
    champs_pj_en_erreur = set()

    # Utilisé pour regarder le différentiel en BDD et supprimer d'éventuels écarts
    liste_id_ds = []
    liste_docs = set()

    # Liste de titres de PJ uniques pour tous les dossier_champs (pj) d'un dossier
    LISTE_TITRES_DOC_UNIQUES = []

    # ID du champ de la dernière itération
    last_id_ch = None

    # Compteur de PJS pour le cas ou un dossier_champ contient plusieurs PJ
    cpt_meme_ch = 0

    def enregistrer_modification_formulaire(date_saisie, id_champ_ds):
        """Retient une seule date pour la future action de timeline."""
        nonlocal date_modification_formulaire, champs_modifies_formulaire
        if getattr(getattr(dossier, "id_etape_dossier", None), "etape", None) != "En attente de compléments":
            return
        if jour_derniere_demande_complements is None:
            return
        try:
            date_modification = parse_datetime_with_tz(date_saisie)
            date_depot = parse_datetime_with_tz(dossier.date_depot)
        except (TypeError, ValueError, OverflowError):
            return
        if (date_modification and date_depot and date_modification > date_depot
                and date_modification.date() >= jour_derniere_demande_complements):
            champs_modifies_formulaire.add(id_champ_ds)
            if date_modification_formulaire is None or date_modification > date_modification_formulaire:
                date_modification_formulaire = date_modification

    for ch in dossier_champs:
        champ_obj = document_obj = None
        dossier_champ = ch["champ"]
        liste_id_ds.append(dossier_champ["id_ds"])

        # Si Champ 'Pieces Jointes' avec plusieurs PJ : 
        #   On a 1 dossier_champ par PJ, par contre documents est la liste de tous les 'docs' présent dans le dossier_champ.
        #   documents de la forme : 
        #   [{
        #       "id_format": id,
        #       "id_nature": id,
        #       "url_ds": "url",
        #       "emplacement": f"{emplacement_dossier}Annexes/",
        #       "description": "blabla",
        #       "titre": "xxx.pdf",
        #   }, ...]

        documents = ch.get("documents", [])
        id_champ = get_first_id(Champ, id_ds=dossier_champ["id_ds"], nom=dossier_champ["nom_champ"])
        id_champ_type = Champ.objects.filter(id=id_champ).values_list("id_champ_type_id", flat=True).first()
        type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()


        #################################
        #    CHAMPS AVEC DOCUMENT (PJ)  #
        #################################
        if documents:
            # Si pour un meme dossier_champ, 2 docs ont le meme nom --> on renomme (__copie01.pdf...)
            documents = rendre_titres_uniques(documents)


            # Si il s'agit du meme dossier_champ que le précédent (cas ou plusieurs pj pour un meme champ)
            if last_id_ch == id_champ :
                cpt_meme_ch += 1

            else :
                cpt_meme_ch = 0

            doc = documents[cpt_meme_ch]
            # logger.info(doc["titre"])

            if doc["titre"] not in LISTE_TITRES_DOC_UNIQUES :
                LISTE_TITRES_DOC_UNIQUES.append(doc["titre"])

            else :
                # SI UNE AUTRE PJ D'UN AUTRE DOSSIER_CHAMP PORTE LE MEME NOM --> ON RENOMME (__copie01.pdf...)
                logger.warning(f"[DOSSIER {dossier.numero} - SYNC DOSSIER CHAMP] 2 PJ appartenant a des champs différents, ont le même nom.")
                doc["titre"] = rendre_titre_unique_dans_liste(titre= doc["titre"], titres_existants= LISTE_TITRES_DOC_UNIQUES)

            
            # On regarde si le document existe deja en base (pour éviter des doublons)
            try:

                document_obj = Document.objects.get(
                                emplacement=doc["emplacement"],
                                titre=doc["titre"],
                                id_nature_id=doc["id_nature"],
                                description=doc["description"]
                            )

                if document_obj:
                    liste_docs.add(document_obj.id)

            except Document.DoesNotExist:
                document_obj = None

            except Document.MultipleObjectsReturned:
                # ça ne devrait pas arriver car contrainte d'unicité sur emplacement,titre
                logger.error(
                    f"[SYNC DOSSIER {dossier.numero} CHAMP - PJ] Plusieurs documents trouvés pour emplacement={doc['emplacement']!r}, titre={doc['titre'].rsplit('.', 1)[0]!r}, "
                    f"id_nature={doc['id_nature']!r}, description={doc['description']!r}."
                )

                # on prend le premier
                document_obj = (
                    Document.objects
                    .filter(
                        emplacement=doc["emplacement"],
                        titre=doc["titre"],
                        id_nature_id=doc["id_nature"],
                        description=doc["description"]
                    )
                    .order_by("id")
                    .first()
                )

                if document_obj is not None:
                    liste_docs.add(document_obj.id)


            except Exception as e:
                logger.error(f"Erreur inattendue lors de la récupération du document : {e}")
                document_obj = None
        

            #--------------------------------
            #   LE DOC N'EXISTE PAS EN BASE
            #--------------------------------
            piece_deja_connue = document_obj is not None
            if document_obj is None :
                
                # Repérer le document de même titre ; différer sa suppression
                # jusqu'à la récupération complète de la nouvelle PJ.
                # Exemple quand ça peut arriver : 
                # Si après dépôt du dossier, le demandeur ajoute une nouvelle PJ qui porte le meme nom qu'une PJ deja existante pour un dossier champ plus lointain dans le formulaire.
                document_obj_sans_desc = Document.objects.filter(
                                emplacement=doc["emplacement"],
                                titre=doc["titre"],
                                id_nature_id=doc["id_nature"],
                            ).first()

                # Si un autre document existe avec le meme nom et le meme emplacement --> On renomme avec _2 ou _3 ect..
                # titre_doc = get_nom_disponible(doc["emplacement"], doc["titre"])
                # doc["titre"] = titre_doc


                # Écriture PJ sur le NAS
                chemin_pj = write_pj_volumineuse(doc['emplacement'], doc["titre"], doc["url_ds"], ecrase=True)
                if not chemin_pj:
                    pj_en_erreur.append({
                        "champ": dossier_champ["nom_champ"], "titre": doc["titre"], "url": doc["url_ds"],
                    })
                    champs_pj_en_erreur.add(dossier_champ["id_ds"])
                    logger.error(
                        "[DOSSIER %s - PJ EN ERREUR] Champ %s - %s : récupération impossible ; "
                        "aucun Document ni DossierChamp créé. La synchronisation continue (voir logs PJ HTTP/NAS).",
                        dossier.numero, dossier_champ["nom_champ"], doc["titre"],
                    )
                    # Une PJ ratée compte dans la progression du formulaire et
                    # dans la sélection de la PJ suivante d'un même champ.
                    ordre_number += 1
                    last_id_ch = id_champ
                    continue

                # Remplacer l'ancienne entrée uniquement après récupération
                # complète. Un incident réseau ne supprime pas ses liens.
                if document_obj_sans_desc:
                    logger.warning(
                        "[DOSSIER %s - SYNC DOSSIER CHAMP] Nouvelle PJ de même titre %s : "
                        "ancien document remplacé après récupération réussie.", dossier.numero, doc["titre"],
                    )
                    document_obj_sans_desc.delete()

                # Création du doc avec le bon titre
                document_obj = Document.objects.create(
                    emplacement=doc["emplacement"],
                    titre=doc["titre"],
                    id_nature_id=doc["id_nature"],
                    id_format_id=doc["id_format"],
                    url_ds=doc["url_ds"],
                    description=doc["description"],
                )

                if document_obj:
                    liste_docs.add(document_obj.id)

                logger.info(f"[CREATE] Document ({type_du_champ}) créé pour dossier {dossier.numero} : {document_obj.titre}")

                champ_obj = DossierChamp.objects.filter(
                    id_dossier_id=id_dossier,
                    id_champ_id=id_champ,
                    id_document__isnull=True
                ).order_by("id").first()

            #--------------------------------
            #   LE DOC EXISTE DEJA EN BASE
            #--------------------------------
            else:
                updated_fields = update_fields(document_obj, {
                    "url_ds": doc["url_ds"],
                    "description": doc["description"],
                })
                if updated_fields :
                    document_obj.save()
                    if updated_fields != ['url_ds'] : # url_ds est recalculée à chaque fois, on evite de surcharger les logs
                        logger.info(f"[SAVE] Document mis à jour ({document_obj}, dossier: {dossier.numero}). Champs modifiés : {', '.join(updated_fields)}.")

                champ_obj = DossierChamp.objects.filter(
                    id_dossier_id=id_dossier,
                    id_champ_id=id_champ,
                    id_document_id=document_obj.id,
                ).order_by("id").first()

            
            # Une ligne DossierChamp par PJ conserve sa date indépendamment des
            # modifications du champ global et des dates de fichiers renvoyées par DN.
            pj_deja_liee = piece_deja_connue and champ_obj is not None
            date_pj = (
                champ_obj.date_saisie if pj_deja_liee
                else date_premiere_detection_pj(dossier, dossier_champ["date_saisie"], premier_import)
            )

            # SI LE DOSSIER CHAMPS EXISTE EN BASE
            if champ_obj:
                champs_a_mettre_a_jour = {
                    "valeur": dossier_champ["valeur"],
                    "geometrie": dossier_champ.get("geometrie"),
                    "id_document_id": document_obj.id,
                    "ordre": ordre_number,
                }
                if not pj_deja_liee:
                    champs_a_mettre_a_jour["date_saisie"] = date_pj

                updated_fields = update_fields(
                    champ_obj, champs_a_mettre_a_jour, date_fields=["date_saisie"],
                )

                champ_obj.save()

                if updated_fields and updated_fields not in (['ordre'], ['id_document_id', 'ordre']) :

                    if not pj_deja_liee and not premier_import:
                        enregistrer_modification_formulaire(date_pj, dossier_champ["id_ds"])

                    logger.info(f"[SAVE] DossierChamp (champ: {champ_obj}) mis à jour avec PJ. Champs modifiés : {', '.join(updated_fields)}.")
            else:
                champ_obj = DossierChamp.objects.create(
                    id_dossier_id=id_dossier,
                    id_champ_id=id_champ,
                    id_document_id=document_obj.id,
                    valeur=dossier_champ["valeur"],
                    date_saisie=date_pj,
                    geometrie=dossier_champ.get("geometrie"),
                    ordre=ordre_number,
                )
                if not premier_import:
                    enregistrer_modification_formulaire(date_pj, dossier_champ["id_ds"])
                logger.info(f"[CREATE] Nouveau DossierChamp (champ: {champ_obj}) avec PJ.")


        #################################
        #    CHAMPS SANS DOCUMENT (PJ)  #
        #################################
        else:
            cpt_meme_ch = 0

            champ_obj, created = DossierChamp.objects.get_or_create(
                id_dossier_id=id_dossier,
                id_champ_id=id_champ,
                id_document_id=None,
                defaults={
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": dossier_champ["date_saisie"],
                    "geometrie": dossier_champ.get("geometrie"),
                    "geometrie_a_saisir": dossier_champ.get("geometrie_a_saisir") if dossier_champ.get("geometrie_a_saisir") else False,
                    "ordre": ordre_number,
                }
            )

            if created:
                logger.info(f"[CREATE] DossierChamp (champ: {champ_obj}) sans PJ créé.")
                enregistrer_modification_formulaire(
                    dossier_champ["date_saisie"], dossier_champ["id_ds"],
                )
                
                # Manifestations Sportives
                if dossier_champ["nom_champ"] == "Numéro du dossier sur la plateforme déclaration-manifestations":
                    num_doss_dm = dossier_champ["valeur"]
                    if num_doss_dm:
                        try:
                            # Cherche le dossier manifestation existant
                            dossier_dm = DossierManifSportive.objects.get(numero_dossier_declaration_manifestations=int(num_doss_dm))

                            # Vérifie si une liaison existe déjà
                            liaison_existe = DossierManifestationLiaison.objects.filter(id_dossier_manif=dossier_dm).exists()

                            # if liaison_existe:
                            #     logger.error(f"[Dossier {dossier.numero}] DossierManifSportive numéro {num_doss_dm} est déjà lié à un dossier DS alors que le DossierChamp 'Numéro du dossier sur la plateforme déclaration-manifestations' apparaît en création ici.")
                            if not liaison_existe:
                                DossierManifestationLiaison.objects.create(id_dossier_id=id_dossier,id_dossier_manif=dossier_dm)
                                logger.info(f"[CREATE] Lien DossierManifSportive ({num_doss_dm}) <--> Dossier DS ({dossier.numero})")

                        except DossierManifSportive.DoesNotExist:
                            logger.warning(f"Aucun DossierManifSportive trouvé avec numéro {num_doss_dm}")
                        except Exception as e:
                            logger.error(f"Liaison DossierManifSportive ({num_doss_dm}) <--> Dossier DS ({dossier.numero}) : {e}")

            else:
                updated_fields, change_num_doss_dm = update_fields_dossier_champs(champ_obj, {
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": dossier_champ["date_saisie"],
                    "geometrie": dossier_champ.get("geometrie"),
                    "ordre": ordre_number,
                }, date_fields=["date_saisie"])

                champ_obj.save()

                if updated_fields and updated_fields not in (['ordre'], ['id_document_id', 'ordre']) :

                    enregistrer_modification_formulaire(
                        dossier_champ["date_saisie"], dossier_champ["id_ds"],
                    )

                    logger.info(f"[SAVE] DossierChamp (champ: {champ_obj.id_champ.nom}, dossier: {dossier.numero}) sans PJ mis à jour. Champs modifiés : {', '.join(updated_fields)}.")

                    # si 'Numéro du dossier sur la plateforme déclaration-manifestations' in updated_fields
                    if change_num_doss_dm != {} and 'valeur' in updated_fields:

                        nouveau_num = change_num_doss_dm.get("new_num_dossDM")
                        ancien_num = change_num_doss_dm.get("old_num_dossDM")

                        logger.info(f"[Dossier {dossier.numero}] Numéro du dossier déclaration-manifestations changé de {ancien_num} à {nouveau_num}")

                        try:
                            # Si elle existe, suppression de DossierManifestationLiaison de l'ancien Numéro du dossier déclaration-manifestations
                            dossier_dm_ancien_num = DossierManifSportive.objects.filter(numero_dossier_declaration_manifestations=int(ancien_num)).first()

                            liaisonManifSportive_ancien_num = None
                            if dossier_dm_ancien_num :
                                logger.warning(f"[Dossier {dossier.numero}] Numéro du dossier déclaration-manifestations changé : Un DossierManif existe avec l'ancien numéro ({ancien_num})")

                                liaisonManifSportive_ancien_num = DossierManifestationLiaison.objects.filter(id_dossier_manif=dossier_dm_ancien_num,id_dossier=dossier).first()

                            if liaisonManifSportive_ancien_num :
                                liaisonManifSportive_ancien_num.delete()
                                logger.warning(f"[Dossier {dossier.numero}] Numéro du dossier déclaration-manifestations changé : Suppression du DossierManifestationLiaison de l'ancien numéro ({ancien_num})")


                            # Vérification si DossierManifSportive existant avec le nouveau numéro
                            dossier_dm = DossierManifSportive.objects.filter(numero_dossier_declaration_manifestations=int(nouveau_num)).first()

                            liaison_existe_dossDM = None
                            liaison_existe = None
                            if dossier_dm :
                                logger.info(f"[Dossier {dossier.numero}] Numéro du dossier déclaration-manifestations changé : Un DossierManif existe avec ce numéro")
                                
                                # Vérification si DossierManifestationLiaison existante pour notre DossierManifSportive (nouveau num)
                                liaison_existe_dossDM = DossierManifestationLiaison.objects.filter(id_dossier_manif=dossier_dm).exists()

                                # Vérification si DossierManifestationLiaison existante pour notre DossierManifSportive (nouveau num) et Dossier
                                liaison_existe= DossierManifestationLiaison.objects.filter(id_dossier_manif=dossier_dm, id_dossier=dossier).exists()
                                
                            # Vérification si DossierManifestationLiaison existante pour notre Dossier
                            liaison_existe_dossDS = DossierManifestationLiaison.objects.filter(id_dossier=dossier).exists()

                            
                            if liaison_existe_dossDS and not liaison_existe :
                                logger.error(f"[Dossier {dossier.numero}] Numéro du dossier déclaration-manifestations changé ({nouveau_num}) : DossierManifestationLiaison déjà existant pour le Dossier")

                            elif liaison_existe_dossDM and not liaison_existe :
                                logger.error(f"[Dossier {dossier.numero}] Numéro du dossier déclaration-manifestations changé ({nouveau_num}) : DossierManifestationLiaison déjà existant pour le DossierManifSportive {nouveau_num}")
                        
                            elif liaison_existe :
                                logger.error(f"[Dossier {dossier.numero}] Numéro du dossier déclaration-manifestations changé ({nouveau_num}) : Un DossierManifLiaison existe deja entre les 2 dossiers")
                            
                            elif dossier_dm:
                                DossierManifestationLiaison.objects.create(id_dossier=dossier, id_dossier_manif=dossier_dm)
                                logger.info(f"[Dossier {dossier.numero}] Numéro du dossier déclaration-manifestations changé ({nouveau_num}) : DossierManifLiaison créée")
                    
                        except DossierManifSportive.DoesNotExist:
                            logger.warning(f"[Dossier {dossier.numero}] Numéro du dossier déclaration-manifestations changé : Aucun DossierManifSportive trouvé avec le numéro {nouveau_num}")
                        except Exception as e:
                            logger.error(f"Erreur Création de liaison suite à modif déclaration-manifestations pour Dossier {dossier.numero} : {e}")
                        
        ordre_number+=1
        last_id_ch = id_champ

    # --------------------------------------------------------------------------------------------
    # Suppression éventuelle de champs suite à une modification du dossier DS par le pétitionnaire.
    # --------------------------------------------------------------------------------------------
    
    # recup tous les dossiers champs du dossier en BDD
    dossier_champs_doss = DossierChamp.objects.filter(id_dossier=dossier)

    # dossier_champs_norma_ds = dossier_champs
    
    # liste_id_ds = []
    # liste_docs = [None]
    # for c in dossier_champs_norma_ds :
    #     liste_id_ds.append(c["champ"]["id_ds"])
    #     documents = c.get("documents", [])
    #     documents = rendre_titres_uniques(documents)
    #     for doc in documents:
    #         if doc :
    #             document_obj = Document.objects.get(
    #                                     emplacement=doc["emplacement"],
    #                                     titre=doc["titre"],
    #                                     id_nature_id=doc["id_nature"],
    #                                     description=doc["description"]
    #                                 )
                

    #             if document_obj.id not in liste_docs :
    #                 liste_docs.append(document_obj.id)

    for d in dossier_champs_doss :
        if d.id_champ.id_ds in champs_pj_en_erreur:
            # Différer le nettoyage de ce champ jusqu'à une synchro complète.
            continue
        if (d.id_champ.id_ds not in liste_id_ds) or (d.id_document and d.id_document.id not in liste_docs) :
            d.delete()
            logger.info(f"[DELETE] DossierChamp (titre: {d.id_champ.nom}, valeur: {d.valeur}, dossier: {dossier.numero}) suite à modifications du pétitionnaire.")



    # ------------------------------------------------------------------------
    # DATE PRÉVISIONNELLE D'ACTIVITÉ
    # ------------------------------------------------------------------------
    # La liste des sources est chargée une seule fois par synchronisation de
    # démarche (dans sync_dossiers), puis réutilisée pour tous ses dossiers.
    # On exploite les champs DN déjà normalisés plutôt que de relire les
    # DossierChamp en BDD pour chaque dossier.
    if date_activite_champs:
        date_debut_activite = nom_champ_source = None
        dossier_dm = None
        for source in date_activite_champs:
            if source.source == "dm":
                if dossier_dm is None:
                    liaison = DossierManifestationLiaison.objects.filter(
                        id_dossier=dossier
                    ).select_related("id_dossier_manif").first()
                    dossier_dm = liaison.id_dossier_manif if liaison else False
                valeur = getattr(dossier_dm, source.champ_dm, None) if dossier_dm else None
                if valeur is None:
                    continue
                try:
                    date_debut_activite = valeur if hasattr(valeur, "tzinfo") else parser_date_activite(str(valeur))
                    nom_champ_source = f"DM · {source.champ_dm}"
                    break
                except (TypeError, ValueError, OverflowError):
                    continue
            elif source.id_champ:
                date_debut_activite, nom_champ_source = extraire_date_debut_activite(
                    [(source.id_champ.id_ds, source.id_champ.nom)], dossier_champs
                )
                if date_debut_activite:
                    break
        if dossier.date_debut_activite != date_debut_activite:
            Dossier.objects.filter(pk=dossier.pk).update(
                date_debut_activite=date_debut_activite,
            )
            if date_debut_activite:
                logger.info(
                    "[DOSSIER %s] Date prévisionnelle d'activité mise à jour depuis le champ %r : %s.",
                    dossier.numero,
                    nom_champ_source,
                    date_debut_activite.isoformat(),
                )
            else:
                logger.info(
                    "[DOSSIER %s] Date prévisionnelle d'activité vidée : aucun champ configuré ne contient de date exploitable.",
                    dossier.numero,
                )


    if date_modification_formulaire and champs_modifies_formulaire:
        instructeur = Instructeur.objects.order_by("id").first()
        if instructeur:
            nombre_champs = len(champs_modifies_formulaire)
            description = (
                "1 champ concerné" if nombre_champs == 1
                else f"{nombre_champs} champs concernés"
            )
            safe_enregistrer_action(
                dossier,
                instructeur,
                "Formulaire modifié",
                request=None,
                description=description,
                date=date_modification_formulaire,
            )
        else:
            logger.warning(
                "[DOSSIER %s - FORMULAIRE MODIFIÉ] Action non enregistrée : aucun instructeur disponible.",
                dossier.numero,
            )
        notifier_formulaire_modifie(dossier, champs_modifies_formulaire, date_modification_formulaire)

    return {"success": not pj_en_erreur, "pj_en_erreur": pj_en_erreur}


