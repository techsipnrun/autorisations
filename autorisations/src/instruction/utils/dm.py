
import os

from django.contrib import messages
from django.db import transaction
from django.utils import timezone
import smbclient

from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierManifSportiveDocument
from autorisations.models.models_instruction import AvisManifSportive, DossierManifSportive, DossierManifestationLiaison, EtapeDossier
from autorisations.models.models_utilisateurs import EmailOutbox, Groupeinstructeur, GroupeinstructeurInstructeur, Instructeur
from autorisations.utils.nas_fonctions import _normalize_unc_path, copier_dossier_smb, ecrire_file_sur_nas, supprimer_dossier_smb_recursif
from declaration_manifestations.get_methods import ajouter_pj_avis, get_access_token, rendre_avis
from instruction.utils.document_utils import normaliser_emplacement
from instruction.utils.dossier_utils import redirect_error, redirect_info
from instruction.utils.files_utils import sanitiser_nom_fichier, valider_fichiers_dm
from synchronisation.utils.fichiers import get_nom_disponible


def user_est_autorise_a_agir_reception_manif_sportive(user) -> bool:
    """
    Retourne True si l'utilisateur est autorisé à agir sur les dossiers
    Déclaration Manifestations en réception.
    """

    if not user or not user.is_authenticated or not user.email:
        return False

    if user.is_superuser :
        return True

    email = user.email.strip().lower()
    instructeur_connecte = Instructeur.objects.filter(email__iexact=email).first()
    if not instructeur_connecte:
        return False
    

    # Cas 1 : Groupe Django Réception SAADD
    if user.groups.filter(name="Réception SAADD").exists():
        return True

    # Cas 2 : Groupe instructeur "Manifestations sportives"
    groupe_manif = Groupeinstructeur.objects.filter(nom="Manifestations sportives").first()
    if not groupe_manif:
        return False

    return GroupeinstructeurInstructeur.objects.filter(
        id_instructeur=instructeur_connecte,
        id_groupeinstructeur=groupe_manif
    ).exists()




# ==========================================
# LECTURE DES DONNÉES DU FORMULAIRE DM
# ==========================================
def reception_lire_donnees_formulaire_avis_dm(request, *, acte_obligatoire=False, label_action, logger):
    """
    Récupère et prépare les données du formulaire de dépôt d’un avis DM (réception).

    Args:
        request (HttpRequest): Requête Django contenant les données POST et FILES.
        acte_obligatoire (bool, optional): Indique si un fichier "acte" est requis.
        label_action (str, optional): Libellé utilisé dans les logs pour identifierl’action en cours (ex: "Avis défavorable", "Non Concerné").
        logger (logging.Logger, optional): Logger utilisé pour tracer les événements.

    Returns:
        tuple:
            - donnees (dict): Dictionnaire contenant :
                - prescriptions (str)
                - dossier_dm_id (str)
                - fichiers (list)
                - acte (UploadedFile | None)
                - fichiers_a_traiter (list)
            - erreur (HttpResponse | None):
                None si tout est valide, sinon une réponse prête à être retournée.
    """
    prescriptions = request.POST.get("prescriptions", "").strip()
    dossier_dm_id = request.POST.get("dossierDM_id")
    fichiers = request.FILES.getlist("files")
    acte = request.FILES.get("acte")
    dossier_dn_accepte_id = request.POST.get("dossier_dn_accepte_id")
    dossier_dn_refuse_id = request.POST.get("dossier_dn_refuse_id")
    

    fichiers_a_traiter = list(fichiers)

    if acte:
        fichiers_a_traiter.append(acte)
    elif acte_obligatoire:
        logger.warning(
            f"[Dossier DM Réception - {label_action}] Utilisateur : {request.user}. "
            f"Pas de soumission car aucun acte n'a été joint."
        )
        return None, redirect_error(request, "Vous devez joindre un acte pour effectuer cette action sur Déclaration Manifestations.")

    donnees = {
        "prescriptions": prescriptions,
        "dossier_dm_id": dossier_dm_id,
        "fichiers": fichiers,
        "acte": acte,
        "fichiers_a_traiter": fichiers_a_traiter,
        "dossier_dn_accepte_id": dossier_dn_accepte_id,
        "dossier_dn_refuse_id": dossier_dn_refuse_id,
    }

    return donnees, None




# ==========================================
# VÉRIFICATION DES DROITS ET DES FICHIERS DM
# ==========================================
def reception_verifier_acces_et_fichiers_avis_dm(request, *, fichiers, label_action, logger):
    """
    Vérifie que l'utilisateur est autorisé à agir sur la réception DM
    et que les fichiers joints respectent les règles métier.

    Args:
        request (HttpRequest): Requête Django de l'utilisateur connecté.
        fichiers (list): Liste des fichiers à valider.
        label_action (str): Libellé utilisé dans les logs
            (ex: "Avis défavorable", "Non Concerné").
        logger (logging.Logger): Logger utilisé pour tracer les événements.

    Returns:
        HttpResponse | None:
            - None si tout est valide
            - une réponse redirect_error prête à être retournée en cas d'erreur
    """
    # Vérification : Personne autorisée ?
    if not user_est_autorise_a_agir_reception_manif_sportive(request.user):
        logger.warning(f"[Dossier DM Réception - {label_action}] Utilisateur non autorisé : {request.user}.")
        return redirect_error(request, "Vous n'êtes pas autorisé à effectuer cette action.")

    # Vérifications : Taille - Extension PJS
    try:
        max_file_size = 5 * 1024 * 1024  # 5 Mo
        extensions_ok = {"pdf", "doc", "docx", "odt", "jpg", "jpeg", "png", "xls", "xlsx"}
        valider_fichiers_dm(fichiers, max_file_size, extensions_ok)
        
    except ValueError as e:
        logger.warning(f"[Dossier DM Réception - {label_action}] Utilisateur : {request.user}. Validation PJ refusée : {e}")
        return redirect_error(request, str(e))

    return None



# =========================================================
# CHARGEMENT DU DOSSIER DM ET DE L'AVIS ASSOCIÉ SOUS VERROU
# =========================================================
def reception_charger_contexte_avis_dm(request, *, dossier_dm_id, nom_etape_cible, label_action, logger):
    """
    Charge et verrouille en base le dossier DM et l'avis associé avant dépôt
    d'un avis depuis la Réception.

    Args:
        request (HttpRequest): Requête Django de l'utilisateur connecté.
        dossier_dm_id (str): Identifiant du dossier DM transmis par le formulaire.
        nom_etape_cible (str): Nom de l'étape à appliquer au dossier (ex: "Refusé", "Accepté", "Non soumis à autorisation").
        label_action (str): Libellé utilisé dans les logs (ex: "Avis défavorable", "Avis favorable", "Non Concerné").
        logger (logging.Logger): Logger utilisé pour tracer les événements.

    Returns:
        tuple:
            - contexte (dict):
                - dossier_dm
                - avis_dm
                - avis_id
                - num_dossier_dm
            - erreur (HttpResponse | None):
                None si tout est valide, sinon une réponse redirect_error
                prête à être retournée.

    Notes:
        - Le dossier DM et l'avis associé sont récupérés avec select_for_update() pour éviter les accès concurrents.
        - La fonction vérifie aussi qu'aucun avis n'a déjà été rendu.
    """
    if not dossier_dm_id:
        logger.error(f"[Dossier DM Réception - {label_action}] Utilisateur : {request.user}. ID du dossier Déclaration Manifestations manquant dans le formulaire.")
        return None, redirect_error(request, "ID du dossier Déclaration Manifestations manquant dans le formulaire. Contactez le support.")

    etape_cible = EtapeDossier.objects.get(etape=nom_etape_cible)

    # Récupération du dossier DM
    dossier_dm = DossierManifSportive.objects.select_for_update().filter(id=dossier_dm_id).first()
    if not dossier_dm:
        logger.error(f"[Dossier DM Réception - {label_action}] Utilisateur : {request.user}. Dossier Déclaration Manifestations (id={dossier_dm_id}) introuvable en base.")
        return None, redirect_error(request, f"Dossier Déclaration Manifestations (id={dossier_dm_id}) introuvable en base. Contactez le support.")

    num_dossier_dm = dossier_dm.numero_dossier_declaration_manifestations

    # Récupération de l'avis associé
    avis_dm = AvisManifSportive.objects.select_for_update().filter(id_dossier_manif_sportive=dossier_dm).first()
    if not avis_dm:
        logger.error(f"[Dossier DM {num_dossier_dm} - Réception - {label_action}] Utilisateur : {request.user}. Aucun Avis DM associé au Dossier DM.")
        return None, redirect_error(request, f"Aucun avis associé au dossier Déclaration Manifestations n° {num_dossier_dm}. Contactez le support.")

    avis_id = avis_dm.id_avis_manif_sportive
    logger.info(f"[Dossier DM {num_dossier_dm} - Réception] Utilisateur : {request.user}. Tentative de déposer un avis {label_action.lower()} sur DM.")

    # Erreur si Avis déjà rendu sur DM
    if avis_dm.date_reponse:
        logger.error(f"Impossible de mettre l'avis DM {avis_id} en '{label_action.lower()}', celui-ci a déjà été rendu (etat = {avis_dm.etat}, date_reponse = {avis_dm.date_reponse}).")
        return None, redirect_error(request, f"Impossible de déposer l'avis DM en '{label_action.lower()}' sur Déclaration Manifestations, celui-ci est déjà rendu ou archivé. Contactez le support.")

    contexte = {
        "dossier_dm": dossier_dm,
        "avis_dm": avis_dm,
        "avis_id": avis_id,
        "num_dossier_dm": num_dossier_dm,
        "etape_cible": etape_cible,
    }

    return contexte, None
    


# ==========================================
# RENDU DE L'AVIS DM ET MISE À JOUR EN BASE
# ==========================================
def reception_rendre_avis_et_mettre_a_jour_dm(*, prescriptions, code_avis_dm, reponse_avis_bdd, contexte, logger):
    """
    Rend l'avis sur Déclaration Manifestations puis met à jour l'avis et le
    dossier en base.

    Args:
        prescriptions (str): Texte transmis au demandeur avec l'avis.
        code_avis_dm (int): Code de réponse attendu par l'API DM
            (ex: 2 = défavorable, 3 = non concerné).
        reponse_avis_bdd (str): Valeur à enregistrer en base dans avis_dm.reponse_avis
            (ex: "défavorable", "non concerné").
        contexte (dict): Dictionnaire contenant :
            - dossier_dm
            - avis_dm
            - avis_id
            - num_dossier_dm
            - etape_cible
        logger (logging.Logger): Logger utilisé pour tracer les événements.

    Returns:

        token (str): Jeton d'accès API récupéré pour la suite des traitements.
    """
    dossier_dm = contexte["dossier_dm"]
    avis_dm = contexte["avis_dm"]
    avis_id = contexte["avis_id"]
    num_dossier_dm = contexte["num_dossier_dm"]
    etape_cible = contexte["etape_cible"]
    
    
    # Récupération du token API
    token = get_access_token()
    
    if not prescriptions :
        prescriptions = ""

    # 0-None, 1-favorable, 2-défavorable, 3-non concerné
    response_avis = rendre_avis(token, avis_id, code_avis_dm, prescriptions)

    logger.info(f"Avis '{reponse_avis_bdd}' soumis avec succès sur DM (avis_id={avis_id}). Réponse API : {response_avis}")

    # ------------------
    # MAJ Avis DM en BDD
    # ------------------
    avis_dm.date_reponse = timezone.now()
    avis_dm.reponse_avis = reponse_avis_bdd
    avis_dm.prescriptions = prescriptions
    avis_dm.save(update_fields=["date_reponse", "prescriptions", "reponse_avis"])
    logger.info(f"Avis DM {avis_id} mis à jour en base.")

    # ---------------------
    # MAJ Dossier DM en BDD
    # ---------------------
    dossier_dm.archive = True
    dossier_dm.id_etape = etape_cible
    dossier_dm.save(update_fields=["archive", "id_etape"])
    logger.info(f"Dossier DM {num_dossier_dm} mis à jour en base (etape : {etape_cible.etape}, archive : True)")

    return token



# ==========================================
# PRÉPARATION DES CHEMINS NAS DU DOSSIER DM
# ==========================================
def reception_preparer_emplacements_dossier_dm(request, *, dossier_dm, sous_dossier_cible, label_action, logger):
    """
    Prépare les chemins source et cible du dossier DM sur le NAS.

    Args:
        request (HttpRequest): Requête Django de l'utilisateur connecté.
        dossier_dm (DossierManifSportive): Dossier DM concerné.
        sous_dossier_cible (str | None): Sous-dossier cible à insérer entre la racine et le nom du dossier (ex: "1 - Hors coeur"). Si None, le dossier est placé directement sous la racine annuelle.
        label_action (str): Libellé utilisé dans les logs (ex: "Avis défavorable", "Non Concerné").
        logger (logging.Logger): Logger utilisé pour tracer les événements.

    Returns:
        tuple:
            - contexte_paths (dict):
                - root_folder
                - ancien_emplacement_dm
                - ancien_emplacement_full_path
                - nouvel_emplacement
                - nouvel_emplacement_full_path
                - racine
                - nom_dossier
            - erreur (HttpResponse | None):
                None si tout est valide, sinon une réponse redirect_error
                prête à être retournée.
    """
    root_folder = os.environ.get("NAS_ROOT")
    ancien_emplacement_dm = dossier_dm.emplacement.replace("\\", "/")

    if not root_folder:
        logger.error(f"[Dossier DM Réception - {label_action}] Erreur lors du déplacement du dossier {ancien_emplacement_dm} sur le NAS : la variable d'environnement 'NAS_ROOT' est vide.")
        msg = (
            f"Avis rendu. Cependant le dossier n'a pas été déplacé sur le NAS, "
            f"il est toujours à l'emplacement {ancien_emplacement_dm}. "
            "Les pièces jointes, s'il y en avait, n'ont pas été déposées sur Déclaration Manifestations. "
            "Le chemin d'accès au NAS n'a pas pu être récupéré. Contactez le support."
        )
        return None, redirect_error(request, msg)

    ancien_emplacement_full_path = os.path.join(root_folder, ancien_emplacement_dm)

    parts = ancien_emplacement_dm.strip("/").split("/")
    if len(parts) < 3:
        logger.error(f"[Dossier DM Réception - {label_action}] Erreur lors du déplacement du dossier {ancien_emplacement_dm} sur le NAS : le path est censé avoir au moins 3 étages (Manifestations_sportives/2026/...).")
        msg = (
            f"Avis rendu. Cependant le dossier n'a pas été déplacé sur le NAS, "
            f"il est toujours à l'emplacement {ancien_emplacement_full_path}. "
            "Les pièces jointes, s'il y en avaient, n'ont pas été déposées sur Déclaration Manifestations, "
            "vous pouvez réessayer de les déposer. Contactez le support."
        )
        return None, redirect_error(request, msg)

    racine = os.path.join(parts[0], parts[1])
    nom_dossier = parts[-1]

    if sous_dossier_cible:
        nouvel_emplacement = os.path.join(racine, sous_dossier_cible, f"{nom_dossier}/")
    else:
        nouvel_emplacement = os.path.join(racine, f"{nom_dossier}/")

    nouvel_emplacement_full_path = os.path.join(root_folder, nouvel_emplacement)

    contexte_paths = {
        "root_folder": root_folder,
        "ancien_emplacement_dm": ancien_emplacement_dm,
        "ancien_emplacement_full_path": ancien_emplacement_full_path,
        "nouvel_emplacement": nouvel_emplacement,
        "nouvel_emplacement_full_path": nouvel_emplacement_full_path,
        "racine": racine,
        "nom_dossier": nom_dossier,
    }

    return contexte_paths, None



# ==========================================================
# TRAITEMENT D'UN FICHIER JOINT POUR UN AVIS DM
# ==========================================================
def reception_traiter_fichier_avis_dm(request, *, fichier, token, avis_id, dossier_dm, root_folder, nouvel_emplacement, sous_dossier_cible, nature_document, description_document, message_erreur_metier, logger):
    """
    Traite un fichier joint lié à un avis DM :
    - dépôt sur Déclaration Manifestations ;
    - écriture sur le NAS ;
    - création du document en base ;
    - liaison avec le dossier DM.

    Args:
        request (HttpRequest): Requête Django de l'utilisateur connecté.
        fichier (UploadedFile): Fichier à traiter.
        token (str): Jeton d'accès API DM.
        avis_id (int): Identifiant de l'avis DM.
        dossier_dm (DossierManifSportive): Dossier DM concerné.
        root_folder (str): Racine absolue du NAS.
        nouvel_emplacement (str): Emplacement relatif cible du dossier DM.
        sous_dossier_cible (str): Sous-dossier cible dans lequel enregistrer le fichier (ex: "Actes/", "Annexes/Instruction/").
        nature_document (str): Nature documentaire à rechercher en base (ex: "Arrêté directeur", "Annexe instructeur DM").
        description_document (str): Description à enregistrer sur le Document créé.
        message_erreur_metier (str): Message métier à afficher si l'écriture NAS échoue.
        logger (logging.Logger): Logger utilisé pour tracer les événements.

    Returns:
        HttpResponse | None:
            - None si tout s'est bien passé ou si seul l'enregistrement BDD a échoué
            - une réponse redirect_error si l'envoi sur Déclaration Manifestations a échoué
    """
    try:
        response_pj = ajouter_pj_avis(token, avis_id, fichier)
        if hasattr(fichier, "seek"):
            fichier.seek(0)

        logger.info(f"PJ '{fichier.name}' ajoutée avec succès à l'avis DM {avis_id}. Réponse API : {response_pj}")

    except Exception as e:
        logger.error(f"Erreur lors de l'ajout de la PJ '{fichier.name}' sur l'avis DM {avis_id} : {e}")
        return redirect_error(request, f"Erreur lors de l'ajout de la pièce jointe '{fichier.name}' sur Déclaration Manifestations. Contactez le support si besoin.")

    nouvel_emplacement_fichier_full_path = os.path.join(root_folder, nouvel_emplacement, sous_dossier_cible)
    nouvel_emplacement_fichier_rel_path = os.path.join(nouvel_emplacement, sous_dossier_cible)

    nom_fichier_sain = sanitiser_nom_fichier(fichier.name)
    titre_doc = get_nom_disponible(nouvel_emplacement_fichier_rel_path, nom_fichier_sain)

    if not ecrire_file_sur_nas(fichier, os.path.join(nouvel_emplacement_fichier_full_path, titre_doc)):
        logger.error(f"Échec de l’écriture du fichier {titre_doc} sur {nouvel_emplacement_fichier_full_path}")
        messages.error(request, f"Erreur lors de l’écriture du fichier {titre_doc} sur {nouvel_emplacement_fichier_full_path}. {message_erreur_metier}")
        return None

    extension = os.path.splitext(titre_doc)[1].lower().lstrip(".")
    doc_format = DocumentFormat.objects.filter(format__iexact=extension).first()
    doc_nature = DocumentNature.objects.filter(nature__iexact=nature_document).first()

    if not doc_format or not doc_nature:
        logger.error(
            f"Fichier {titre_doc} écrit à l'emplacement {nouvel_emplacement_fichier_rel_path}, "
            f"mais le document n'a pas été créé en base car la nature ({doc_nature}) "
            f"ou le format ({doc_format}) est introuvable."
        )
        return None

    defaults = {
        "id_format": doc_format,
        "id_nature": doc_nature,
        "description": description_document,
    }

    doc, created = Document.objects.get_or_create(emplacement=nouvel_emplacement_fichier_rel_path, titre=titre_doc, defaults=defaults,)

    DossierManifSportiveDocument.objects.get_or_create(id_dossier_manif_sportive=dossier_dm, id_document=doc,)

    return None



# Documents déposés dur DM par instructeur
def documents_deposes_sur_DM(doss_manif_sportive):
    """
    Args:
        doss_manif_sportive (DossierManifSportive): Dossier DM
    
    Returns:
        pjs_demandeur_DM (list Document) : Liste des PJ du demandeur sur DM
        actes_deposes_sur_DM (list Document) : Liste des actes déposés par l'instructeur sur DM
        annexes_deposees_sur_DM (list Document) : Liste des annexes déposées par l'instructeur sur DM
    """

    actes_natures = {"Avis conforme", "Avis simple", "Déliberation CA", "Arrêté directeur",}
    documents_DM = [ d.id_document for d in DossierManifSportiveDocument.objects.filter( id_dossier_manif_sportive=doss_manif_sportive)]

    pjs_demandeur_DM = [
        doc for doc in documents_DM
        if doc.id_nature.nature == "Pièce jointe demandeur"
    ]
    
    actes_deposes_sur_DM = [
        doc for doc in documents_DM
        if doc.id_nature.nature in actes_natures
    ]

    annexes_deposees_sur_DM = [
        doc for doc in documents_DM
        if doc.id_nature.nature == "Annexe instructeur" or doc.id_nature.nature == "Annexe instructeur DM"
    ]

    # On récupère le path du Dossier
    chemin_complet_DM = doss_manif_sportive.emplacement
    if not chemin_complet_DM.startswith(os.getenv('NAS_ROOT')):
        chemin_complet_DM = os.path.join(os.getenv('NAS_ROOT'), chemin_complet_DM)
    chemin_complet_DM = _normalize_unc_path(chemin_complet_DM)


    return {
            'annexes_deposees_sur_DM': annexes_deposees_sur_DM,
            'actes_deposes_sur_DM': actes_deposes_sur_DM,
            'pjs_demandeur_DM': pjs_demandeur_DM,
            'chemin_complet_DM': chemin_complet_DM,
            }




def _get_contexte_dossier_dm(dossier, request, logger, action_log, message_succes_dn, message_erreur_dm):
    """
    Récupère le dossier Déclaration Manifestations lié au dossier DN ainsi que l'avis associé.

    Args:
        dossier (Dossier): Dossier DN en cours de traitement.
        request: Requête HTTP Django.
        logger: Logger à utiliser.
        action_log (str): Libellé métier pour les logs (ex: "Envoi acte d'acceptation", "Envoi acte de refus","Classement comme 'Non soumis à autorisation'").
        message_succes_dn (str): Début du message métier côté DN (ex: "Le dossier a bien été accepté sur Démarche Numérique").
        message_erreur_dm (str): Partie spécifique du message d'erreur DM.

    Returns:
        tuple:
            - dict | None : {
                "liaison": liaison_dossDN,
                "dossier_dm": dossier_dm,
                "num_dossier_dm": num_dossier_dm,
                "avis_dm": avis_dm,
                "avis_id": avis_id,
              }
            - HttpResponseRedirect | None : redirect_error si anomalie métier
    """
    if dossier.id_demarche.type.lower() != "manifestations sportives":
        return None, None

    liaison_dossDN = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()
    if not liaison_dossDN:
        return None, None

    dossier_dm_id = liaison_dossDN.id_dossier_manif.id

    dossier_dm = DossierManifSportive.objects.filter(id=dossier_dm_id).first()
    if not dossier_dm:
        logger.error(f"[DOSSIER {dossier.numero}] {action_log} ({request.user}) : Dossier Déclaration Manifestations (id={dossier_dm_id}) introuvable en base.")
        return None, redirect_error(request, f"{message_succes_dn}, mais {message_erreur_dm}. Contactez le support.")

    num_dossier_dm = dossier_dm.numero_dossier_declaration_manifestations

    avis_dm = AvisManifSportive.objects.filter(id_dossier_manif_sportive=dossier_dm).first()
    if not avis_dm:
        logger.error(f"[DOSSIER {dossier.numero}] {action_log} ({request.user}) : Aucun Avis DM associé au Dossier DM {num_dossier_dm}.")
        return None, redirect_error(
            request,
            f"{message_succes_dn}, mais l'avis n'a pas pu être rendu sur Déclaration Manifestations pour le dossier n° {num_dossier_dm} "
            f"(aucun avis associé en base). Contactez le support."
        )

    return {
        "liaison": liaison_dossDN,
        "dossier_dm": dossier_dm,
        "num_dossier_dm": num_dossier_dm,
        "avis_dm": avis_dm,
        "avis_id": avis_dm.id_avis_manif_sportive,
    }, None



def _soumettre_avis_dm(*, dossier, request, logger, action_log, message_succes_dn, contexte_dm, code_avis_dm, libelle_avis_dm, etape_cible_label, motivation=None,):
    """
    Rend un avis sur Déclaration Manifestations et met à jour la base locale.

    Args:
        dossier (Dossier): Dossier DN.
        request: Requête HTTP Django.
        logger: Logger à utiliser.
        action_log (str): Libellé métier pour les logs.
        message_succes_dn (str): Message d'introduction pour redirect_error.
        contexte_dm (dict): Résultat de _get_contexte_dossier_dm.
        code_avis_dm (int): Code API DM (1=favorable, 2=défavorable, 3=non concerné).
        libelle_avis_dm (str): Libellé stocké en base ("favorable", "défavorable", "non concerné").
        etape_cible_label (str): Libellé exact de l'étape cible ("Accepté", "Refusé", "Non soumis à autorisation").
        motivation (str | None): Motivation/prescriptions.

    Returns:
        tuple:
            - dict | None :
                {
                    "token": token,
                    "avis_id": avis_id,
                    "avis_dm": avis_dm,
                    "dossier_dm": dossier_dm,
                    "num_dossier_dm": num_dossier_dm,
                    "deja_rendu": bool,
                }
          
            - HttpResponseRedirect | None : redirect_error si erreur métier/technique
    """
    avis_dm = contexte_dm["avis_dm"]
    avis_id = contexte_dm["avis_id"]
    dossier_dm = contexte_dm["dossier_dm"]
    num_dossier_dm = contexte_dm["num_dossier_dm"]

    if avis_dm.date_reponse:
        logger.warning(f"[DOSSIER {dossier.numero}] {action_log} ({request.user}) : Avis (avis_id={avis_id}) déjà soumis sur DM.")

        messages.info(request, f"Aucun changement sur Déclaration Manifestations, un avis '{avis_dm.reponse_avis}' a déjà été rendu.")

        if not dossier_dm.archive:
            dossier_dm.archive = True
            dossier_dm.save(update_fields=["archive"])

        return {
            "token": None,
            "avis_id": avis_id,
            "avis_dm": avis_dm,
            "dossier_dm": dossier_dm,
            "num_dossier_dm": num_dossier_dm,
            "deja_rendu": True,
        }, None

    try:
        token = get_access_token()
        motivation = motivation or ""

        response_avis = rendre_avis(token, avis_id, code_avis_dm, motivation)
        logger.info(
            f"[DOSSIER {dossier.numero}] {action_log} ({request.user}) : "
            f"Avis '{libelle_avis_dm}' soumis avec succès sur DM (avis_id={avis_id}). "
            f"Réponse API : {response_avis}"
        )

        avis_dm.date_reponse = timezone.now()
        avis_dm.reponse_avis = libelle_avis_dm
        avis_dm.prescriptions = motivation
        avis_dm.save(update_fields=["date_reponse", "prescriptions", "reponse_avis"])
        logger.info(f"Avis DM {avis_id} mis à jour en base.")

        etape_cible = EtapeDossier.objects.get(etape=etape_cible_label)
        dossier_dm.archive = True
        dossier_dm.id_etape = etape_cible
        dossier_dm.save(update_fields=["archive", "id_etape"])
        logger.info(f"Dossier DM {num_dossier_dm} mis à jour en base (etape : {etape_cible.etape}, archive : True)")

        return {
            "token": token,
            "avis_id": avis_id,
            "avis_dm": avis_dm,
            "dossier_dm": dossier_dm,
            "num_dossier_dm": num_dossier_dm,
            "deja_rendu": False,
        }, None

    except Exception as e:
        erreur = str(e)

        logger.error(
            f"[DOSSIER {dossier.numero}] {action_log} ({request.user}) : "
            f"Erreur lors de la soumission de l'avis '{libelle_avis_dm}' sur Déclaration Manifestations : {e}"
        )

        if "406 Client Error" in erreur:
            return None, redirect_info(
                request, f"{message_succes_dn}, en revanche l'avis n'a pas pu être rendu sur Déclaration Manifestations "
                         f"puisqu'il a déjà été rendu. Vous pouvez, si vous le souhaitez, déposer l'acte sur la plateforme via le bouton : 'Déposer des pièces jointes sur Déclaration Manifestations'"
            )
        else :

            return None, redirect_error(request, f"{message_succes_dn}, mais l'avis n'a pas pu être rendu sur Déclaration Manifestations. Contactez le support.")
    



def get_nb_relances(dm):
    """
    Retourne le nombre de mails de relance envoyés pour un dossierDéclaration Manifestations.

    Args:
        dm (DossierManifSportive): le dossier DM concerné

    Returns:
        int: nombre de relances envoyées
    """
    return EmailOutbox.objects.filter(
        id_dossier_dm=dm.id,
        type_mail="Relance",
        statut="Envoyé"
    ).count()
