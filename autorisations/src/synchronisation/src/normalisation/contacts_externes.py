from synchronisation.src.functions import clean_email, clean_name
from synchronisation.src.functions import get_first_id
from autorisations.models.models_utilisateurs import TypeContactExterne


def contact_externe_normalize(doss):
    """ 
    Normalise les contacts externes : Bénéficiaire et Demandeur intermédiaire.
    """

    contacts_externes = {
        'beneficiaire': {},
        'demandeur_intermediaire': {}
    }

    # Si un mandataire est présent
    if doss.get("prenomMandataire") and doss.get("nomMandataire"):

        contacts_externes['demandeur_intermediaire'] = {
            "email": clean_email(doss['usager']['email']),
            "id_type": get_first_id(TypeContactExterne, type="demandeur_intermediaire"),
            "nom": clean_name(doss['nomMandataire']),
            "prenom": clean_name(doss['prenomMandataire']),
        }

        email_benef = None
        if doss['demandeur']['__typename'] == "PersonnePhysique":
            email_benef = clean_email(doss['demandeur']['email'])

        contacts_externes['beneficiaire'] = {
            "email": email_benef,
            "id_type": get_first_id(TypeContactExterne, type="beneficiaire"),
            "nom": clean_name(doss['demandeur']['nom']),
            "prenom": clean_name(doss['demandeur']['prenom']),
        }

    else:
        # Si pas de mandataire, le demandeur est le bénéficiaire
        contacts_externes['beneficiaire'] = {
            "email": clean_email(doss['usager']['email']),
            "id_type": get_first_id(TypeContactExterne, type="beneficiaire"),
            "nom": clean_name(doss['demandeur']['nom']),
            "prenom": clean_name(doss['demandeur']['prenom']),
        }

    return contacts_externes
