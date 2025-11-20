import logging

from django.shortcuts import redirect
from autorisations.models.models_instruction import Dossier, Message
from django.contrib import messages

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


def safe_enregistrer_action(dossier, instructeur, action, request, description=None, date=None):
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



