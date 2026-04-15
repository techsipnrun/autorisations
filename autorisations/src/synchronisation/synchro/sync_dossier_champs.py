import json
import os
from autorisations.models.models_instruction import Dossier, DossierChamp, Champ, ChampType, DossierManifSportive, DossierManifestationLiaison
from autorisations.models.models_documents import Document
from autorisations.models.models_utilisateurs import DossierInstructeur
from notifications.service import compute_dedupe_key, create_EmailOutbox, envoi_mail
from ..utils.model_helpers import get_first_id, update_fields, update_fields_dossier_champs
from ..utils.fichiers import rendre_titre_unique_dans_liste, write_pj, rendre_titres_uniques, write_pj_volumineuse
import logging
from autorisations.settings import EMAIL_NOTIF_TEST, NOTIFS_PROD

logger = logging.getLogger("SYNCHRONISATION")
loggerMail = logging.getLogger("MAIL")


def sync_dossier_champs(dossier_champs, id_dossier):
    """
    Synchronise les DossierChamps avec ou sans pièce(s) jointe(s).
    """
    dossier = Dossier.objects.get(id=id_dossier)
    ordre_number = 0
    notif_demande_de_compléments = False

    # Utilisé pour regarder le différentiel en BDD et supprimer d'éventuels écarts
    liste_id_ds = []
    liste_docs = set()

    # Liste de titres de PJ uniques pour tous les dossier_champs (pj) d'un dossier
    LISTE_TITRES_DOC_UNIQUES = []

    # ID du champ de la dernière itération
    last_id_ch = None

    # Compteur de PJS pour le cas ou un dossier_champ contient plusieurs PJ
    cpt_meme_ch = 0

    for ch in dossier_champs:
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

                liste_docs.add(document_obj.id)


            except Exception as e:
                logger.error(f"Erreur inattendue lors de la récupération du document : {e}")
                document_obj = None
        

            #--------------------------------
            #   LE DOC N'EXISTE PAS EN BASE
            #--------------------------------
            if document_obj is None :
                
                # Si un autre doc existe (même emplacement, même titre) : on le supprime, il sera logiquement recréé ensuite avec un nouveau titre
                # Exemple quand ça peut arriver : 
                # Si après dépôt du dossier, le demandeur ajoute une nouvelle PJ qui porte le meme nom qu'une PJ deja existante pour un dossier champ plus lointain dans le formulaire.
                document_obj_sans_desc = Document.objects.filter(
                                emplacement=doc["emplacement"],
                                titre=doc["titre"],
                                id_nature_id=doc["id_nature"],
                            ).first()

                if document_obj_sans_desc:
                    logger.warning(f"[DOSSIER {dossier.numero} - SYNC DOSSIER CHAMP] Après dépôt du dossier, le demandeur a ajouté une nouvelle PJ qui porte le meme nom qu'une PJ déjà "
                                "existante pour un dossier_champ plus lointain dans le formulaire. On supprime le doc de ce dossier_champ plus lointain, il sera recréé avec un autre nom.")
                    document_obj_sans_desc.delete()


                # Si un autre document existe avec le meme nom et le meme emplacement --> On renomme avec _2 ou _3 ect..
                # titre_doc = get_nom_disponible(doc["emplacement"], doc["titre"])
                # doc["titre"] = titre_doc


                # Écriture PJ sur le NAS
                if write_pj_volumineuse(doc['emplacement'], doc["titre"], doc["url_ds"], ecrase=True) :

                    # Création du doc avec le bon titre
                    document_obj = Document.objects.create(
                                    emplacement=doc["emplacement"],
                                    titre=doc["titre"],
                                    id_nature_id=doc["id_nature"],
                                    id_format_id=doc["id_format"],
                                    url_ds=doc["url_ds"],
                                    description=doc["description"]
                                )
                    
                    if document_obj:
                        liste_docs.add(document_obj.id)

                    logger.info(f"[CREATE] Document ({type_du_champ}) créé pour dossier {dossier.numero} : {document_obj.titre}")

                    champ_obj = DossierChamp.objects.filter(
                        id_dossier_id=id_dossier,
                        id_champ_id=id_champ,
                        id_document__isnull=True
                    ).order_by("id").first()

                # Erreur lors de l'écriture de la PJ sur le NAS
                else :
                    logger.error(f"[DOSSIER {dossier.numero} - SYNC DOSSIER CHAMP] Erreur lors de l'écriture de la PJ {doc['titre']}. Le DossierChamp et le Document n'ont pas été créés en base.")


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

            
            # SI LE DOSSIER CHAMPS EXISTE EN BASE
            if champ_obj:
                updated_fields = update_fields(champ_obj, {
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": dossier_champ["date_saisie"],
                    "geometrie": dossier_champ.get("geometrie"),
                    "id_document_id": document_obj.id,
                    "ordre": ordre_number,
                }, date_fields=["date_saisie"])

                champ_obj.save()

                if updated_fields and updated_fields not in (['ordre'], ['id_document_id', 'ordre']) :

                    if dossier.id_etape_dossier.etape == "En attente de compléments" :
                        notif_demande_de_compléments = True

                    logger.info(f"[SAVE] DossierChamp (champ: {champ_obj}) mis à jour avec PJ. Champs modifiés : {', '.join(updated_fields)}.")
            else:
                champ_obj = DossierChamp.objects.create(
                    id_dossier_id=id_dossier,
                    id_champ_id=id_champ,
                    id_document_id=document_obj.id,
                    valeur=dossier_champ["valeur"],
                    date_saisie=dossier_champ["date_saisie"],
                    geometrie=dossier_champ.get("geometrie"),
                    ordre=ordre_number,
                )
                if dossier.id_etape_dossier.etape == "En attente de compléments" :
                    notif_demande_de_compléments = True
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
                if dossier.id_etape_dossier.etape == "En attente de compléments" :
                        notif_demande_de_compléments = True
                
                # Manifestations Sportives
                if dossier_champ["nom_champ"] == "Numéro du dossier sur la plateforme déclaration-manifestations":
                    num_doss_dm = dossier_champ["valeur"]
                    if num_doss_dm:
                        try:
                            # Cherche le dossier manifestation existant
                            dossier_dm = DossierManifSportive.objects.get(numero_dossier_declaration_manifestations=int(num_doss_dm))

                            # Vérifie si une liaison existe déjà
                            liaison_existe = DossierManifestationLiaison.objects.filter(id_dossier_manif=dossier_dm).exists()

                            if liaison_existe:
                                logger.error(f"[Dossier {dossier.numero}] DossierManifSportive numéro {num_doss_dm} est déjà lié à un dossier DS alors que le DossierChamp 'Numéro du dossier sur la plateforme déclaration-manifestations' apparaît en création ici.")
                            else:
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
                    
                    if dossier.id_etape_dossier.etape == "En attente de compléments" :
                        notif_demande_de_compléments = True

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
        if (d.id_champ.id_ds not in liste_id_ds) or (d.id_document and d.id_document.id not in liste_docs) :
            d.delete()
            logger.info(f"[DELETE] DossierChamp (titre: {d.id_champ.nom}, valeur: {d.valeur}, dossier: {dossier.numero}) suite à modifications du pétitionnaire.")




    #######################
    # NOTIFICATION PAR MAIL 
    #######################
    # Notifier les instructeurs que le pétitionnaire a modifié son dossier suite à la demande de compléments
    if notif_demande_de_compléments :

        # On notifie les agents dans le cadre d'une vraie instruction
        if NOTIFS_PROD :
            emails_norm = (DossierInstructeur.objects.filter(id_dossier=dossier).values_list("id_instructeur__email", flat=True))
        # Test de notification par mail à EMAIL_NOTIF_TEST   
        else :
            emails_norm = [EMAIL_NOTIF_TEST]



        # if (DossierAvis.objects.filter(id_avis=avis).exists() or avis.id_dossier):
        sujet = f"Dossier n° {dossier.numero} - {dossier.id_demarche.type} : Dossier modifié suite à une demande de compléments"
        
        context = {
                "dossier_numero": dossier.numero,
                "demarche_type": dossier.id_demarche.type,
                "url": f"{os.getenv('URL_APPLI')}instruction/{dossier.numero}/"
            }

        template_name = "dossier_modifie" 
        dedupe = compute_dedupe_key(emails_norm, sujet, template_name, context)
        outbox = create_EmailOutbox(emails_norm, sujet, template_name, dedupe, context, None, type_mail = "Notification")

        if outbox :
            ok, err = envoi_mail(outbox.id)
        else :
            loggerMail.error(f"[DOSSIER {dossier.numero}] Dossier modifié suite à une demande de compléments : Erreur lors de la création de l'EmailOutbox, {', '.join(outbox.to)} n'a pas été notifié par mail.")

        if ok:
            loggerMail.info(f"[DOSSIER {dossier.numero}] Notification Email {outbox.id} (Dossier modifié suite à une demande de compléments) envoyée à {', '.join(outbox.to)} ")
        else:
            loggerMail.error(f"[DOSSIER {dossier.numero}] Échec envoi notification email {outbox.id} (Dossier modifié suite à une demande de compléments) à {', '.join(outbox.to)} : {err}")


    logger.info(' ----- ')
