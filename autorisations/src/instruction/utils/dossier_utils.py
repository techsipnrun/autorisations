import ast
import json
import logging
from django.utils import timezone

from django.shortcuts import redirect
from autorisations.models.models_instruction import Dossier, DossierAction, Message
from django.contrib import messages

from autorisations.models.models_utilisateurs import DossierBeneficiaire
from instruction.utils_instru import changer_etape_si_differente, changer_etat_si_different, enregistrer_action

logger = logging.getLogger("ORM_DJANGO")


def redirect_error(request, msg):
    messages.error(request, msg)
    return redirect(request.META.get("HTTP_REFERER", "/"))


EXCLUDED_EMAILS = ["contact@demarches-simplifiees.fr",]
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


def safe_enregistrer_action(dossier, instructeur, action, request, description=None, date=timezone.now()):
    """
    Enregistre une action sur un dossier avec gestion des erreurs.
    Pour rappel : enregistrer_action(dossier, instructeur, nom_action, description=None, date=None)
    """

    try:
        enregistrer_action(dossier, instructeur, action, description, date)
        return None
    except Exception as e:
        logger.error(f"[DOSSIER {dossier.numero}] Erreur lors de l’enregistrement de l’action '{action}' par {request.user} -  : {e}")
        messages.error(request, "Erreur lors de l’enregistrement de l’action. Contactez le support.")
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
            champs_prepares.append({"type": "champ", "nom": nom, "valeur": champ.valeur or "Non renseigné",})

    return champs_prepares, nb_cartes




# instruction/services/etapes_service.py

def get_etapes_custom(present_sur_ds: bool, etape_actuelle: str, demarche_type: str):
    """Retourne les actions possibles pour chaque étape."""

    etapes_ds_present = {

        "À affecter": ["Passer en pré-instruction", "Classer le dossier comme non soumis à autorisation"],

        "En pré-instruction": ["Demander des compléments", "Classer le dossier comme non soumis à autorisation",
                               "Classer le dossier comme refusé", "Passer en instruction"],

        "En attente de compléments": ["Passer en instruction"],

        "En instruction": ["Demander des compléments", "Classer le dossier comme non soumis à autorisation",
                           "Classer le dossier comme refusé", "Faire valider une demande d'avis",
                           "Faire valider le projet d'acte"],

        "À valider avant demande d'avis": ["Repasser en instruction",
                                          "Valider le modèle de demande d'avis et le projet d'acte"],

        "À valider avant signature": ["Repasser en instruction", "Valider et envoyer pour relecture qualité"],

        "En relecture qualité": ["Repasser en instruction", "Prêt à la signature"],

        "En attente réponse d'avis": ["Envoyer les modifications de l'acte pour validation",
                                      "Acte inchangé, envoyer pour relecture qualité"],

        "Avis à envoyer": ["Avis envoyé"],

        "En attente de signature": ["Repasser en instruction", "Acte prêt à être envoyé",
                                    "Classer le dossier comme non soumis à autorisation",
                                    "Classer le dossier comme refusé"],

        "Acte à envoyer": ["Envoyer l'acte"],

        "À publier au RAA": ["Classer le dossier comme accepté"],

        "Non soumis à autorisation": ["Repasser en instruction"],

        "Accepté": ["Repasser en instruction"],

        "Refusé": ["Repasser en instruction"],
    }

    etapes_ds_supprime = {
        "À affecter": ["Passer en pré-instruction", "Classer le dossier comme non soumis à autorisation"],

        "En pré-instruction": ["Classer le dossier comme non soumis à autorisation",
                               "Classer le dossier comme refusé", "Passer en instruction"],

        "En attente de compléments": [],

        "En instruction": ["Classer le dossier comme non soumis à autorisation", "Classer le dossier comme refusé",
                           "Faire valider une demande d'avis", "Faire valider le projet d'acte"],

        "À valider avant demande d'avis": ["Valider le modèle de demande d'avis et le projet d'acte"],

        "À valider avant signature": ["Valider et envoyer pour relecture qualité",
                                      "Classer le dossier comme non soumis à autorisation",
                                      "Classer le dossier comme refusé"],

        "En relecture qualité": ["Prêt à la signature", "Classer le dossier comme non soumis à autorisation",
                                 "Classer le dossier comme refusé"],

        "En attente réponse d'avis": ["Envoyer les modifications de l'acte pour validation",
                                      "Acte inchangé, envoyer pour relecture qualité",
                                      "Classer le dossier comme non soumis à autorisation",
                                      "Classer le dossier comme refusé"],

        "Avis à envoyer": ["Avis envoyé", "Classer le dossier comme non soumis à autorisation",
                           "Classer le dossier comme refusé"],

        "En attente de signature": ["Acte prêt à être envoyé",
                                    "Classer le dossier comme non soumis à autorisation",
                                    "Classer le dossier comme refusé"],

        "Acte à envoyer": ["Envoyer l'acte", "Classer le dossier comme non soumis à autorisation",
                           "Classer le dossier comme refusé"],

        "À publier au RAA": ["Classer le dossier comme accepté",
                             "Classer le dossier comme non soumis à autorisation",
                             "Classer le dossier comme refusé"],

        "Non soumis à autorisation": [],

        "Accepté": [],

        "Refusé": [],
    }

    etapes = etapes_ds_present if present_sur_ds else etapes_ds_supprime

    # Cas spécial : manifestations sportives
    if etape_actuelle == "En instruction" and demarche_type == "Manifestations sportives":
        etapes["En instruction"] = [
            a for a in etapes["En instruction"]
            if a != "Envoyer pour validation avant demande d'avis"
        ]

    return etapes



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
}


def build_timeline_for_dossier(dossier):
    actions = DossierAction.objects.filter(id_dossier=dossier).order_by("-date")

    for a in actions:
        a.logo = LOGO_MAPPING.get(a.id_action.action, "timeline.png")

    return actions