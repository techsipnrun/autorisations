import ast
from datetime import timedelta
import json
import logging
from django.utils import timezone

from django.shortcuts import redirect
from autorisations.models.models_instruction import ActionsPossibles, AvisManifSportive, Demarche, Dossier, DossierAction, DossierManifSportive, DossierManifestationLiaison, Message, SynchronisationEtat
from django.contrib import messages

from autorisations.models.models_utilisateurs import DossierBeneficiaire, DossierInterlocuteur
from instruction.utils_instru import changer_etape_si_differente, changer_etat_si_different, enregistrer_action
from django.db.models import Q



logger = logging.getLogger("ORM_DJANGO")


def redirect_error(request, msg):
    messages.error(request, msg)
    return redirect(request.META.get("HTTP_REFERER", "/"))

def redirect_warning(request, msg):
    messages.warning(request, msg)
    return redirect(request.META.get("HTTP_REFERER", "/"))

def redirect_info(request, msg):
    messages.info(request, msg)
    return redirect(request.META.get("HTTP_REFERER", "/"))


EXCLUDED_EMAILS = ["contact@demarches-simplifiees.fr", "contact@demarche.numerique.gouv.fr"]
EXCLUDED_SUFFIXES = ["reunion-parcnational.fr"]


def count_unread_messages_for_dossier(dossier, num_dossier: int | None = None) -> int:
    """
    Retourne le nombre de messages non lus pour un dossier.
    Exclut les messages DS et les messages internes selon les règles métier.

    Ne lève jamais d’exception :
    en cas d'erreur → log + renvoie 0.
    """
    try:
        qs = Message.objects.filter(id_dossier=dossier, lu=False)

        # Exclure les messages DS
        for email in EXCLUDED_EMAILS:
            qs = qs.exclude(email_emetteur=email)

        # Exclure les messages internes "finissant par"
        for suffix in EXCLUDED_SUFFIXES:
            qs = qs.exclude(email_emetteur__endswith=suffix)

        return qs.count()

    except Exception as e:
        dossier_id = num_dossier or (getattr(dossier, "numero", None) or dossier.id)
        logger.error(f"[DOSSIER {dossier_id}] Erreur lors du calcul des messages non lus : {e}")
        return 0


def get_dossier_or_redirect(request, etape, id_ds=None, numero=None):
    dossier = None
    if id_ds:
        dossier = Dossier.objects.filter(id_ds=id_ds).first()
    if numero:
        dossier = Dossier.objects.filter(numero=numero).first()

    if not dossier:
        if id_ds:
            logger.error(f"[{etape}] Dossier id_ds = {id_ds} introuvable  (user={request.user})")
        elif numero :
            logger.error(f"[{etape}] Dossier numero={numero} introuvable  (user={request.user})")
            
        messages.error(request, "Dossier introuvable. Contactez le support.")
        return None, redirect(request.META.get("HTTP_REFERER", "/"))
    return dossier, None



def safe_update_etape(dossier, nouvelle_etape, request, break_si_erreur):
    try:
        changer_etape_si_differente(dossier, nouvelle_etape, request.user, request)
        return None
    
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Échec MAJ étape '{nouvelle_etape}' par {request.user} : {e}")
        messages.error(request, "Erreur lors de la mise à jour de l’étape du dossier. Contactez le support.")
        if break_si_erreur :
            return redirect(request.META.get("HTTP_REFERER", "/"))
        else :
            return None



def safe_update_etat(dossier, nouvel_etat, request, break_si_erreur):
    try:
        changer_etat_si_different(dossier, nouvel_etat, request.user)
        return None
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Échec MAJ état '{nouvel_etat}' par {request.user} (Fait sur DS par contre) : {e}")
        messages.error(request, "Erreur lors de la mise à jour de l’état. Contactez le support.")
        if break_si_erreur :
            return redirect(request.META.get("HTTP_REFERER", "/"))
        else :
            return None


def safe_enregistrer_action(dossier, instructeur, action, request, description=None, date=None):
    """
    Enregistre une action sur un dossier avec gestion des erreurs.
    Pour rappel : enregistrer_action(dossier, instructeur, nom_action, description=None, date=None)
    """

    if date is None:
        date = timezone.now()

    try:
        enregistrer_action(dossier, instructeur, action, description, date)
        return None
    except Exception as e:
        if request :
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l’enregistrement de l’action '{action}' par {request.user} -  : {e}")
            messages.error(request, "Erreur lors de l’enregistrement de l’action. Contactez le support.")
        else :
            logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l’enregistrement de l’action '{action}' -  : {e}")
            
        return None


def set_dossier_role(model, dossier, instructeur, role_label, request):
    """
    Supprime les éventuels instructeurs ayant deja ce role
    Attribue le rôle à un unique instructeur 
    
    model      : modèle (ex : DossierSignataire)
    dossier    : instance Dossier
    instructeur: instance Instructeur à affecter
    role_label : label textuel pour logs
    """

    try:
        # suppression des anciens
        model.objects.filter(id_dossier=dossier).delete()

        # création du nouveau
        model.objects.create(id_dossier=dossier, id_instructeur=instructeur)

        logger.info(f"[DOSSIER {dossier.numero}] {instructeur} (Rôle = {role_label}) affecté au dossier.")
        return None
    
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l'affectation du rôle '{role_label}' à {instructeur} : {e}")
        return redirect_error(request,f"❌ Erreur lors de l'affectation du rôle '{role_label}' à instructeur. Contactez le support.")



def get_beneficiaire_for_dossier(dossier):
    """
    Retourne l'objet bénéficiaire d'un dossier (ou None).
    """
    try:
        benef = (
            DossierBeneficiaire.objects
            .select_related("id_beneficiaire", "id_dossier_interlocuteur")
            .filter(id_dossier_interlocuteur__id_dossier=dossier)
            .first()
        )
        return benef.id_beneficiaire if benef else None
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de la récupération du Bénéficiaire : {e}")
        return None
    

def get_demandeur_for_dossier(dossier):
    """
    Retourne l'objet ContactExterne demandeur d'un dossier (ou None).
    Règle :
      - si un demandeur intermédiaire existe → on le retourne
      - sinon → le demandeur est le bénéficiaire
    """
    try:
        interlocuteur = (
            DossierInterlocuteur.objects
            .select_related("id_demandeur_intermediaire")
            .filter(id_dossier=dossier)
            .first()
        )

        # 1) Demandeur intermédiaire prioritaire
        if interlocuteur and interlocuteur.id_demandeur_intermediaire:
            return interlocuteur.id_demandeur_intermediaire

        # 2) Sinon : demandeur = bénéficiaire
        benef = (
            DossierBeneficiaire.objects
            .select_related("id_beneficiaire", "id_dossier_interlocuteur")
            .filter(id_dossier_interlocuteur__id_dossier=dossier)
            .first()
        )
        return benef.id_beneficiaire if benef else None

    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de la récupération du Demandeur : {e}")
        return None




def build_champs_prepares(dossier):
    """
    Construit la liste champs_prepares et compte nb_cartes
    à partir des DossierChamp d'un dossier.
    """
    nb_cartes = 0
    champs_prepares = []

    for champ in dossier.dossierchamp_set.select_related("id_champ__id_champ_type").order_by("ordre"):

        ct = champ.id_champ.id_champ_type.type
        nom = champ.id_champ.nom.rstrip(":").strip() if champ.id_champ.nom else ""

        # Ignorer les champs de type explication
        if ct == "explication":
            continue

        # Exclure seulement les checkbox qui commencent par "Je certifie" ou "J'atteste"
        if ct == "checkbox" and (nom.startswith("Je certifie") or nom.startswith("J'atteste")):
            continue
        
        # Traduction spécifique pour les champs Oui/Non
        if ct == "yes_no":
            val = (champ.valeur or "").strip().lower()
            champs_prepares.append({
                "type": "champ",
                "nom": nom,
                "valeur": "Oui" if val == "true" else "Non" if val == "false" else "Non renseigné",
            })

        elif ct == "carte" and champ.geometrie:
            nb_cartes += 1
            geojson_source = champ.geometrie_modif or champ.geometrie
            champs_prepares.append({"type": "carte", "nom": nom, "geojson": json.dumps(geojson_source), "id": champ.id})

        elif ct == "header_section":
            champs_prepares.append({"type": "header", "titre": nom})

        elif ct == "piece_justificative":
            if champ.id_document:
                emplacement_doc = champ.id_document.emplacement
                champs_prepares.append({"type": "piece_justificative", "nom": nom, "url": champ.id_document.url_ds, "titre_doc": champ.id_document.titre, "emplacement_doc": emplacement_doc,})
            else:
                champs_prepares.append({"type": "piece_justificative","nom": nom, "titre_doc": "ERROR PARSING URL DS",})

        elif ct == "repetition":
            repetitions = []

            try:
                valeur = ast.literal_eval(champ.valeur) if isinstance(champ.valeur, str) else champ.valeur or {}
            except Exception:
                valeur = {}

            for liste in (valeur or {}).values():
                bloc = [{"nom": item.get("nom"), "valeur": item.get("valeur")} for item in liste]
                repetitions.append(bloc)

            champs_prepares.append({"type": "repetition", "nom": nom, "valeur": repetitions or "Non renseigné",})

        elif ct == "drop_down_list":
            if nom == 'Choix de la méthode pour localiser le projet' and 'Remplir le module de cartographie' not in (champ.valeur or ""):
                geojson_source = champ.geometrie_modif or champ.geometrie
                if not geojson_source:
                    champs_prepares.append({"type": "drop_down_list", "nom": nom, "valeur": champ.valeur, "geometrie_a_saisir": 'oui', "geojson": json.dumps({}), "id": champ.id,})
                else:
                    champs_prepares.append({"type": "drop_down_list", "nom": nom, "valeur": champ.valeur, "geometrie_a_saisir": 'non', "geojson": json.dumps(geojson_source), "id": champ.id,})
            else:
                champs_prepares.append({"type": "drop_down_list", "nom": nom, "valeur": champ.valeur, "geometrie_a_saisir": 'non pas concerné',})

        else:
            champ_prepare = {"type": "champ", "nom": nom, "valeur": champ.valeur or "Non renseigné"}
            if "Numéro du dossier précédent" in nom:
                numero_precedent = str(champ.valeur or "").strip()
                champ_prepare["est_dossier_actuel"] = bool(
                    numero_precedent and numero_precedent == str(dossier.numero)
                )
                champ_prepare["dossier_precedent_existe"] = bool(
                    numero_precedent
                    and not champ_prepare["est_dossier_actuel"]
                    and Dossier.objects.filter(numero=numero_precedent).exists()
                )
            champs_prepares.append(champ_prepare)

    return champs_prepares, nb_cartes




# def get_etapes_custom(present_sur_ds: bool, dossier_sppn: bool, etape_actuelle: str, demarche_type: str):
#     """Retourne les actions possibles pour chaque étape."""

#     # DOSSIER PRESENT SUR DS
#     if present_sur_ds :

#         etapes = {
#             "À affecter": ["Passer en pré-instruction", "Archiver le dossier comme non soumis à autorisation"], OK

#             "En pré-instruction": ["Demander des compléments", "Archiver le dossier comme non soumis à autorisation", "Passer en instruction"],

#             "En attente de compléments": ["Passer en instruction"], OK

#             "En instruction": ["Demander des compléments", "Archiver le dossier comme non soumis à autorisation", 
#                                "Faire valider avant l'envoi d'une demande d'avis à une instance", "Faire valider le projet d'acte"], OK

#             "À valider avant demande d'avis": ["Repasser en instruction",
#                                             "Valider le modèle de demande d'avis et le projet d'acte"],

#             "À valider avant signature": ["Repasser en instruction", "Valider et envoyer pour relecture qualité"], OK

#             "En relecture qualité": ["Repasser en instruction", "Prêt à la signature"], OK

#             "En attente réponse d'avis": ["Envoyer les modifications de l'acte pour validation",
#                                         "Acte inchangé, envoyer pour relecture qualité"],

#             "Avis à envoyer": ["Avis envoyé"],

#             "En attente de signature": ["Repasser en instruction", "Acte prêt à être envoyé",
#                                         "Archiver le dossier comme non soumis à autorisation"],  OK

#             "Acte à envoyer": ["Envoyer l'acte d'acceptation", "Envoyer l'acte de refus"], OK

#             "À publier au RAA": ["Archiver le dossier comme accepté", "Archiver le dossier comme refusé"], OK

#             "Non soumis à autorisation": ["Repasser en instruction"],

#             "Accepté": ["Repasser en instruction"], OK

#             "Refusé": ["Repasser en instruction"],
#         }
        
#         # Etapes simplifiées pour le SPPN
#         if dossier_sppn:
#             # Retiré : "Faire valider une demande d'avis", "Faire valider le projet d'acte"
#             # Ajouté : "Acte prêt à la signature"
#             etapes["En instruction"] = [
#                 "Demander des compléments",
#                 "Archiver le dossier comme non soumis à autorisation",
#                 "Acte prêt à la signature",
#             ]                                          OK


#     # DOSSIER PLUS SUR DS
#     else :
#         actions_classement = [
#             "Archiver le dossier comme accepté",
#             "Archiver le dossier comme non soumis à autorisation",
#             "Archiver le dossier comme refusé",
#         ]                                                    OK
                
#         etapes = {
#             "À affecter": actions_classement,
#             "En pré-instruction": actions_classement,
#             "En attente de compléments": actions_classement,
#             "En instruction": actions_classement,
#             "À valider avant demande d'avis": actions_classement,
#             "À valider avant signature": actions_classement,
#             "En relecture qualité": actions_classement,
#             "En attente réponse d'avis": actions_classement,
#             "Avis à envoyer": actions_classement,
#             "En attente de signature": actions_classement,
#             "Acte à envoyer": actions_classement,
#             "À publier au RAA": actions_classement,
#             "Non soumis à autorisation": [],
#             "Accepté": [],
#             "Refusé": [],
#         }


#     # Cas spécial : manifestations sportives
#     if etape_actuelle == "En instruction" and demarche_type == "Manifestations sportives":
#         etapes["En instruction"] = [
#             a for a in etapes["En instruction"]
#             if a != "Faire valider une demande d'avis"
#         ]

#     return etapes





def get_actions_possibles(dossier: Dossier):
    """
    Retourne la liste des labels d'actions possibles pour un dossier.
    Priorité de recherche :

    # MANIFESTATIONS SPORTIVES
    1. Groupe instructeur, Démarche, coeur_de_parc, (présent sur DN, type_manif_sportive)
    2. Démarche, coeur_de_parc, (présent sur DN, type_manif_sportive)
    3. Démarche, (présent sur DN, type_manif_sportive)
    4. (présent sur DN, type_manif_sportive)
    5. (présent sur DN)

    # HORS MANIFESTATIONS SPORTIVES
    1. Groupe instructeur, Démarche, (présent sur DN)
    2. Démarche, (présent sur DN)
    3. (présent sur DN)

    On s'arrête dès qu'un niveau retourne au moins une règle.
    """

    if not dossier or not dossier.id_etape_dossier:
        return []

    etape_id = dossier.id_etape_dossier_id
    demarche_id = dossier.id_demarche_id
    groupe_id = dossier.id_groupeinstructeur_id
    present_sur_dn = dossier.present_sur_ds

    type_manif_sportive = None
    coeur_de_parc = None

    est_manif_sportive = dossier.id_demarche.type == "Manifestations sportives"


    if est_manif_sportive :
        liaison_existe_dossDN = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()

        if liaison_existe_dossDN :
            type_manif_sportive = "Dossier complet"
            coeur_de_parc = liaison_existe_dossDN.id_dossier_manif.coeur_de_parc

        else :
            type_manif_sportive = "Dossier DN"

        base_qs = (
            ActionsPossibles.objects
            .select_related("id_changement_etape", "id_etape", "id_demarche", "id_groupe_instructeur")
            .filter(id_etape_id=etape_id,)
        )

    else :    
        base_qs = (
            ActionsPossibles.objects
            .select_related("id_changement_etape", "id_etape", "id_demarche", "id_groupe_instructeur")
            .filter(
                id_etape_id=etape_id,
                coeur_de_parc__isnull=True,
                type_manif_sportive__isnull=True,
            )
        )

    niveaux = []


    # print(
    #     f"""
    #     --- DEBUG DOSSIER ---
    #     etape_id              : {etape_id}
    #     demarche_id           : {demarche_id}
    #     groupe_id             : {groupe_id}
    #     present_sur_dn        : {present_sur_dn}
    #     type_manif_sportive   : {type_manif_sportive}
    #     coeur_de_parc         : {coeur_de_parc}
    #     est_manif_sportive    : {est_manif_sportive}
    #     -----------------------
    #     """
    # )


    # ------------------------
    # MANIFESTATIONS SPORTIVES
    # ------------------------
    if est_manif_sportive :

        # Niveau 1 : Groupe instructeur, Démarche, coeur_de_parc, (présent sur DN, type_manif_sportive)
        if groupe_id and demarche_id and type_manif_sportive and coeur_de_parc is not None :
            niveaux.append(
                base_qs.filter(
                    id_groupe_instructeur_id=groupe_id,
                    id_demarche_id=demarche_id,
                    type_manif_sportive=type_manif_sportive,
                    coeur_de_parc=coeur_de_parc,
                    present_sur_dn=present_sur_dn,
                )
            )

        # Niveau 2 : Démarche, coeur_de_parc, (présent sur DN, type_manif_sportive)
        if demarche_id and type_manif_sportive and coeur_de_parc is not None :
            niveaux.append(
                base_qs.filter(
                    id_groupe_instructeur__isnull=True,
                    id_demarche_id=demarche_id,
                    type_manif_sportive=type_manif_sportive,
                    coeur_de_parc=coeur_de_parc,
                    present_sur_dn=present_sur_dn,
                )
            )

        # Niveau 3 : Démarche, (présent sur DN, type_manif_sportive)
        if demarche_id and type_manif_sportive :
            niveaux.append(
                base_qs.filter(
                    id_groupe_instructeur__isnull=True,
                    id_demarche_id=demarche_id,
                    type_manif_sportive=type_manif_sportive,
                    coeur_de_parc__isnull=True,
                    present_sur_dn=present_sur_dn,
                )
            )
        
        # Niveau 4 : (présent sur DN, type_manif_sportive)
        if type_manif_sportive :
            niveaux.append(
                base_qs.filter(
                    id_groupe_instructeur__isnull=True,
                    id_demarche__isnull=True,
                    type_manif_sportive=type_manif_sportive,
                    coeur_de_parc__isnull=True,
                    present_sur_dn=present_sur_dn,
                )
            )
        
        # Niveau 5 : (présent sur DN)
        if type_manif_sportive :
            niveaux.append(
                base_qs.filter(
                    id_groupe_instructeur__isnull=True,
                    id_demarche__isnull=True,
                    type_manif_sportive__isnull=True,
                    coeur_de_parc__isnull=True,
                    present_sur_dn=present_sur_dn,
                )
            )


    # -----------------------------
    # HORS MANIFESTATIONS SPORTIVES
    # -----------------------------
    else :

        # Niveau 1 : Groupe instructeur, Démarche, (présent sur DN)
        if groupe_id and demarche_id:
            niveaux.append(
                base_qs.filter(
                    id_groupe_instructeur_id=groupe_id,
                    id_demarche_id=demarche_id,
                    present_sur_dn=present_sur_dn,
                )
            )

        # Niveau 2 : Démarche, (présent sur DN)
        if demarche_id:
            niveaux.append(
                base_qs.filter(
                    id_groupe_instructeur__isnull=True,
                    id_demarche_id=demarche_id,
                    present_sur_dn=present_sur_dn,
                )
            )

        # Niveau 3 : (présent sur DN)
        niveaux.append(
            base_qs.filter(
                id_groupe_instructeur__isnull=True,
                id_demarche__isnull=True,
                present_sur_dn=present_sur_dn,
            )
        )


    # On execute les requetes SQL et on s'arrete dès qu'un niveau propose un résultat
    for qs in niveaux:
        regles = list(qs)
        if regles:
            # déduplication conservant l'ordre DB
            labels = []
            deja_vus = set()

            for regle in regles:
                label = regle.id_changement_etape.action
                if label not in deja_vus:
                    deja_vus.add(label)
                    labels.append(label)

            return labels

    return []


def get_actions_possibles_DM(dossierDM: DossierManifSportive):
    """
    Retourne la liste des labels d'actions possibles pour un dossier DM (sans DN) qui est en réception.
    Étapes possibles : En réception, Non soumis à autorisation, Refusé, Accepté
    Priorité de recherche :

    1. Démarche, coeur_de_parc, type_manif_sportive, (présent sur DN)
    2. Démarche, type_manif_sportive, (présent sur DN)
    3. Démarche, (présent sur DN)
    4. (présent sur DN)


    On s'arrête dès qu'un niveau retourne au moins une règle.
    """

    if not dossierDM or not dossierDM.id_etape:
        return []

    manif_id = dossierDM.numero_dossier_declaration_manifestations
    etape_id = dossierDM.id_etape_id
    demarche_id = Demarche.objects.get(type="Manifestations sportives").id
    coeur_de_parc = dossierDM.coeur_de_parc
    liaison_existe_dossDM = DossierManifestationLiaison.objects.filter(id_dossier_manif=dossierDM).first()

    if liaison_existe_dossDM :
        logger.error(f"[DOSSIER DM n°{manif_id}] La fonction get_actions_possibles_DM est appelée alors que le dossier DM est lié au Dossier DN n°{liaison_existe_dossDM.id_dossier.numero}")
        return []
    
    else :
        type_manif_sportive = "Dossier DM"
        present_sur_dn = False
  

    base_qs = (
        ActionsPossibles.objects
        .select_related("id_changement_etape", "id_etape", "id_demarche",)
        .filter(id_etape_id=etape_id, id_groupe_instructeur__isnull=True,)
    )

    niveaux = []

    # print(
    #     f"""
    #     --- DEBUG DOSSIER ---
    #     etape_id              : {etape_id}
    #     demarche_id           : {demarche_id}
    #     present_sur_dn        : {present_sur_dn}
    #     type_manif_sportive   : {type_manif_sportive}
    #     coeur_de_parc         : {coeur_de_parc}
    #     -----------------------
    #     """
    # )

    # Niveau 1 : Démarche, coeur_de_parc, type_manif_sportive, (présent sur DN)
    if demarche_id and type_manif_sportive and coeur_de_parc is not None :
        niveaux.append(
            base_qs.filter(
                id_demarche_id=demarche_id,
                type_manif_sportive=type_manif_sportive,
                coeur_de_parc=coeur_de_parc,
                present_sur_dn = present_sur_dn,
            )
        )

    # Niveau 2 : Démarche, type_manif_sportive, (présent sur DN)
    if demarche_id and type_manif_sportive :
        niveaux.append(
            base_qs.filter(
                id_demarche_id=demarche_id,
                type_manif_sportive=type_manif_sportive,
                coeur_de_parc__isnull=True,
                present_sur_dn = present_sur_dn,
            )
        )

    # Niveau 3 : Démarche, (présent sur DN)
    if demarche_id :
        niveaux.append(
            base_qs.filter(
                id_demarche_id=demarche_id,
                type_manif_sportive__isnull=True,
                coeur_de_parc__isnull=True,
                present_sur_dn = present_sur_dn,
            )
        )

    # Niveau 4 : (présent sur DN)
    niveaux.append(
        base_qs.filter(
            id_demarche__isnull=True,
            type_manif_sportive__isnull=True,
            coeur_de_parc__isnull=True,
            present_sur_dn = present_sur_dn,
        )
    )
    


    # On execute les requetes SQL et on s'arrete dès qu'un niveau propose un résultat
    for qs in niveaux:
        regles = list(qs)
        if regles:
            # déduplication conservant l'ordre DB
            labels = []
            deja_vus = set()

            for regle in regles:
                label = regle.id_changement_etape.action
                if label not in deja_vus:
                    deja_vus.add(label)
                    labels.append(label)

            return labels

    return []






LOGO_MAPPING = {
    "Dossier reçu": "recu.png",
    "Instructeur.e retiré.e": "instructeur_retire.png",
    "Instructeur.e ajouté.e": "instructeur_ajoute.png",
    "Classé sans suite": "classe-sans-suite.png",
    "Classé comme refusé": "refuse.png",
    "Classé comme accepté": "accepte.png",
    "Demande de compléments": "demande-de-complements.png",
    "Avis reçu": "recu.png",
    "Avis demandé": "acte-envoye.png",
    "Acte signé": "acte-signe.png",
    "Modification de l'acte": "acte-signe.png",
    "Acte envoyé": "acte-envoye.png",
    "Validé avant demande d'avis": "valide.png",
    "Publié au RAA": "publie_au_raa.png",
    "Prêt à la signature": "envoye.png",
    "Envoyé pour signature": "envoye.png",
    "Relecture qualité": "relecture-qualite.png",
    "Validé avant signature": "valide.png",
    "Relecture": "relecture-qualite.png",
    "Passage en instruction": "envoye.png",
    "Repassage en instruction": "envoye.png",
    "Affectation au groupe": "groupe_instructeur.png",
    "Passage en pré-instruction": "envoye.png",
    "Envoyé pour validation": "envoye_pour_validation.png",
    "Envoyé pour relecture qualité": "envoye.png",
    "Validant.e changé.e": "changer_valideur.png",
    "Relecteur.rice changé.e": "changer_relecteur.png",
    "Intermédiaire signature changé.e": "changer_intermédiaire.png",
    "Envoyeur.se d'acte changé.e": "changer_envoyeur.png",
    "Publieur.se RAA changé.e": "changer_publieurRAA.png",
    "Dossier supprimé de Démarche Numérique": "dossier_supprime_de_DN.png",
}


def build_timeline_for_dossier(dossier):
    actions = DossierAction.objects.filter(id_dossier=dossier).order_by('-date', '-id')

    for a in actions:
        a.logo = LOGO_MAPPING.get(a.id_action.action, "timeline.png")

    return actions




def set_etat_actualisation_dossier(num_dossier, statut=None, message=None):
    """
    statut:
      - "running"
      - "success"
      - "error"
      - None
    """
    Dossier.objects.filter(numero=num_dossier).update(
        actualisation_statut=statut,
        actualisation_date=timezone.now() if statut else None,
        actualisation_message=message,
    )


def get_etat_actualisation_dossier(num_dossier):
    dossier = Dossier.objects.filter(numero=num_dossier).values(
        "actualisation_statut",
        "actualisation_date",
        "actualisation_message",
    ).first()

    if not dossier:
        return {
            "en_cours": False,
            "statut": None,
            "message": "Dossier introuvable",
            "date": None,
        }

    statut = dossier["actualisation_statut"]

    return {
        "en_cours": statut == "running",
        "statut": statut,
        "message": dossier["actualisation_message"],
        "date": dossier["actualisation_date"],
    }


def clear_etat_actualisation_dossier(num_dossier):
    Dossier.objects.filter(numero=num_dossier).update(
        actualisation_statut=None,
        actualisation_date=None,
        actualisation_message=None,
    )


def actualisation_dossier_est_bloquee(dossier, delai_minutes=10):
    if dossier.actualisation_statut != "running":
        return False

    if not dossier.actualisation_date:
        return True

    return timezone.now() - dossier.actualisation_date > timedelta(minutes=delai_minutes)


def set_etat_actualisation_demarche(num_demarche, statut=None, message=None):
    Demarche.objects.filter(numero=num_demarche).update(
        actualisation_statut=statut,
        actualisation_date=timezone.now() if statut else None,
        actualisation_message=message,
    )


def get_etat_actualisation_demarche(num_demarche):
    
    demarche = Demarche.objects.filter(numero=num_demarche).values("actualisation_statut", "actualisation_date", "actualisation_message",).first()

    etat_global = SynchronisationEtat.objects.filter(id=1).values("en_cours").first()
    synchro_globale_en_cours = etat_global["en_cours"] if etat_global else False

    if not demarche:
        return {
            "en_cours": False,
            "statut": None,
            "message": "Démarche introuvable",
            "date": None,
            "synchro_globale_en_cours": synchro_globale_en_cours,
        }

    statut = demarche["actualisation_statut"]

    return {
        "en_cours": statut == "running",
        "statut": statut,
        "message": demarche["actualisation_message"],
        "date": demarche["actualisation_date"],
        "synchro_globale_en_cours": synchro_globale_en_cours,
    }


def clear_etat_actualisation_demarche(num_demarche):
    Demarche.objects.filter(numero=num_demarche).update(
        actualisation_statut=None,
        actualisation_date=None,
        actualisation_message=None,
    )


def actualisation_demarche_est_bloquee(demarche, delai_minutes=30):
    if demarche.actualisation_statut != "running":
        return False

    if not demarche.actualisation_date:
        return True

    return timezone.now() - demarche.actualisation_date > timedelta(minutes=delai_minutes)





def check_si_on_casse_liaison_dm(dossier:Dossier, dossier_dm:DossierManifSportive, liaison:DossierManifestationLiaison, logger):
    """
    Vérifie si la liaison entre un Dossier et un DossierManifSportive doit être cassée.

    Règles métier :
    - Le traitement ne s'applique que si le dossier n'est plus présent sur DN (dossier.present_sur_ds == False).
    - Si un avis a déjà été rendu sur DM (AvisManifSportive.date_reponse non nulle), on ne fait rien.
    - Si aucun avis n'a encore été rendu sur DM : 
        on vérifie que dossier_dm.archive == False ;
        on supprime la DossierManifestationLiaison entre les deux dossiers.

    Args:
        dossier (Dossier)
        dossier_dm (DossierManifSportive)

    Returns:
        bool:
            - True si la liaison a été supprimée,
            - False sinon.
    """

    if not dossier or not dossier_dm:
        logger.error(f"[DOSSIER {dossier_numero} SUPPRIMÉ DE DN] check_si_on_casse_liaison_dm appelée avec un objet dossier ou dossier_dm manquant.")
        return False
    
    if not liaison:
        logger.warning(f"[DOSSIER {dossier_numero} SUPPRIMÉ DE DN] Aucune liaison DM trouvée à supprimer avec le dossier DM {dossier_dm_numero}.")
        return False
    

    dossier_numero = dossier.numero
    dossier_dm_numero = dossier_dm.numero_dossier_declaration_manifestations

    etape_dossier = dossier.id_etape_dossier.etape

    # Récupération de l'avis DM
    avis_dm = AvisManifSportive.objects.filter(id_dossier_manif_sportive=dossier_dm).first()
    avis_dm_numero = avis_dm.id_avis_manif_sportive

    # ----------------------
    # AVIS DEJA RENDU SUR DM
    # ----------------------
    if avis_dm and avis_dm.date_reponse is not None:
        logger.info(f"[DOSSIER {dossier_numero} SUPPRIMÉ DE DN] Liaison DM conservée avec le dossier DM {dossier_dm_numero} : "
                    f"Avis DM {avis_dm_numero} a déjà été rendu le {avis_dm.date_reponse}.")
        return False
    
    # ----------------------
    # AVIS NON RENDU SUR DM
    # ----------------------
    etapes_bloquantes = ["Accepté", "Refusé", "Non soumis", "À publier au RAA"]
    if etape_dossier in etapes_bloquantes:
        logger.warning(
            f"[DOSSIER {dossier_numero} SUPPRIMÉ DE DN] Rupture de liaison DM alors que le dossier est à l'étape "
            f"'{etape_dossier}'. Or, l'avis DM {avis_dm_numero} n'a pas encore été déposé (Dossier DM {dossier_dm_numero}, archive={dossier_dm.archive})."
        )

    # Vérification archive
    if dossier_dm.archive:
        logger.warning(
            f"[DOSSIER {dossier_numero} SUPPRIMÉ DE DN] Avis DM {avis_dm_numero} non rendu, or le dossier DM {dossier_dm_numero} "
            f"est archivé (archive=True). On remet archive à False avant de supprimer la liaison."
        )
        dossier_dm.archive = False
        dossier_dm.save()
 
    
    # Suppression de la liaison
    liaison.delete()
    logger.info(f"[DOSSIER {dossier_numero} SUPPRIMÉ DE DN] Liaison DM supprimée (dossier DM {dossier_dm_numero})")

    return True
