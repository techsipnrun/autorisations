from synchronisation.src.utils.conversion import clean_email, clean_name, clean_surname
from synchronisation.src.utils.model_helpers import get_first_id
from autorisations.models.models_utilisateurs import TypeContactExterne


def contact_externe_normalize(doss):
    """ 
    Normalise les contacts externes : Bénéficiaire et Demandeur intermédiaire.
    """

    contacts_externes = {
        'beneficiaire': {},
        'demandeur_intermediaire': {}
    }

    # Démarche à destination d'une personne physique, avec un demandeur intermédiaire)
    if doss.get("prenomMandataire") and doss.get("nomMandataire"):

        contacts_externes['demandeur_intermediaire'] = {
            "email": clean_email(doss['usager']['email']),
            "id_type": get_first_id(TypeContactExterne, type="demandeur_intermediaire"),
            "nom": clean_surname(doss['nomMandataire']),
            "prenom": clean_name(doss['prenomMandataire']),
        }

        email_benef = None
        if doss['demandeur']['__typename'] == "PersonnePhysique":
            email_benef = clean_email(doss['demandeur']['email'])

        contacts_externes['beneficiaire'] = {
            "email": email_benef,
            "id_type": get_first_id(TypeContactExterne, type="beneficiaire"),
            "nom": clean_surname(doss['demandeur']['nom']),
            "prenom": clean_name(doss['demandeur']['prenom']),
        }

    else:
        # Le demandeur (Physique ou Morale) est le bénéficiaire
        if doss['demandeur']['__typename'] == 'PersonnePhysique' :
            contacts_externes['beneficiaire'] = {
                "email": clean_email(doss['usager']['email']),
                "id_type": get_first_id(TypeContactExterne, type="beneficiaire"),
                "nom": clean_surname(doss['demandeur']['nom']),
                "prenom": clean_name(doss['demandeur']['prenom']),

            }

        if doss['demandeur']['__typename'] == 'PersonneMorale' :

            raison_sociale = doss['demandeur']['entreprise']['raisonSociale'] if doss['demandeur'].get('entreprise') else None
            orga = doss['demandeur']['entreprise']['nom'] if doss['demandeur'].get('entreprise') else (doss['demandeur']['association']['titre'] if doss['demandeur'].get('association') else None)

            contacts_externes['beneficiaire'] = {
                "email": clean_email(doss['usager']['email']),
                "id_type": get_first_id(TypeContactExterne, type="beneficiaire"),
                "nom": raison_sociale or orga or "",
                
                "siret": doss['demandeur']['siret'],
                "raison_sociale": raison_sociale,
                "organisation": orga,
                "adresse": doss['demandeur']['address']['cityName'],
            }

    return contacts_externes
