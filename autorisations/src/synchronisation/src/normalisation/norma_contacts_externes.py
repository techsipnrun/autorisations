import logging
from synchronisation.src.utils.conversion import clean_email, clean_name, clean_surname
from synchronisation.src.utils.model_helpers import get_first_id
from autorisations.models.models_utilisateurs import TypeContactExterne

logger = logging.getLogger('ORM_DJANGO')
def contact_externe_normalize(doss, contacts_externes):
    """ 
    Normalise les contacts externes : Bénéficiaire et Demandeur intermédiaire.
    """

    id_type_demandeur_intermédiaire = get_first_id(TypeContactExterne, type="Demandeur intermédiaire")
    id_type_beneficiaire = get_first_id(TypeContactExterne, type="Bénéficiaire")

    # if contacts_externes :
    #     if contacts_externes.get('beneficiaire') :
    #         if contacts_externes.get('beneficiaire').get('adresse') :
    #             if contacts_externes.get('beneficiaire').get('adresse') == "11 Rue Réaumur 75003 Paris" :
    #                 logger.info('SIMOOOONE MAIL ?')
    #                 logger.info(contacts_externes)

    if not contacts_externes :
        contacts_externes = {
            'beneficiaire': {},
            'demandeur_intermediaire': {}
        }

    # Démarche à destination d'une personne physique, avec un demandeur intermédiaire
    if doss.get("prenomMandataire") and doss.get("nomMandataire"):

        # contacts_externes['demandeur_intermediaire'] = {
        #     "email": clean_email(doss['usager']['email']),
        #     "id_type": get_first_id(TypeContactExterne, type="demandeur_intermediaire"),
        #     "nom": clean_surname(doss['nomMandataire']),
        #     "prenom": clean_name(doss['prenomMandataire']),
        # }

        contacts_externes['demandeur_intermediaire']['email'] = clean_email(doss['usager']['email'])
        contacts_externes['demandeur_intermediaire']['id_type'] = id_type_demandeur_intermédiaire
        contacts_externes['demandeur_intermediaire']['nom'] = clean_surname(doss['nomMandataire'])
        contacts_externes['demandeur_intermediaire']['prenom'] = clean_name(doss['prenomMandataire'])


        if doss['demandeur']['__typename'] == "PersonnePhysique" :
            if clean_email(doss['demandeur']['email']) :
                contacts_externes['beneficiaire']["email"] = clean_email(doss['demandeur']['email'])


        contacts_externes['beneficiaire']["id_type"] = id_type_beneficiaire
        contacts_externes['beneficiaire']["nom"] = clean_surname(doss['demandeur']['nom'])
        contacts_externes['beneficiaire']["prenom"] = clean_name(doss['demandeur']['prenom'])

        # contacts_externes['beneficiaire'] = {
        #     "email": email_benef,
        #     "id_type": get_first_id(TypeContactExterne, type="beneficiaire"),
        #     "nom": clean_surname(doss['demandeur']['nom']),
        #     "prenom": clean_name(doss['demandeur']['prenom']),
        # }

    else:
        # Le demandeur (Physique ou Morale) est le bénéficiaire
        if doss['demandeur']['__typename'] == 'PersonnePhysique' :
            # contacts_externes['beneficiaire'] = {
            #     "email": clean_email(doss['usager']['email']),
            #     "id_type": get_first_id(TypeContactExterne, type="beneficiaire"),
            #     "nom": clean_surname(doss['demandeur']['nom']),
            #     "prenom": clean_name(doss['demandeur']['prenom']),

            # }
            contacts_externes['beneficiaire']["email"] = clean_email(doss['usager']['email'])
            contacts_externes['beneficiaire']["id_type"] = id_type_beneficiaire
            contacts_externes['beneficiaire']["nom"] = clean_surname(doss['demandeur']['nom'])
            contacts_externes['beneficiaire']["prenom"] = clean_name(doss['demandeur']['prenom'])


        if doss['demandeur']['__typename'] == 'PersonneMorale' :

            raison_sociale = doss['demandeur']['entreprise']['raisonSociale'] if doss['demandeur'].get('entreprise') else None
            orga = doss['demandeur']['entreprise']['nom'] if doss['demandeur'].get('entreprise') else (doss['demandeur']['association']['titre'] if doss['demandeur'].get('association') else None)

            if raison_sociale :
                contacts_externes['beneficiaire']["raison_sociale"] = raison_sociale
                
            if orga :
                contacts_externes['beneficiaire']["organisation"] = orga

            contacts_externes['beneficiaire']["email"] = clean_email(doss['usager']['email'])
            contacts_externes['beneficiaire']["id_type"] = id_type_beneficiaire

            if doss['demandeur']['siret'] :
                # logger.info(f"siret : {doss['demandeur']['siret']}")
                contacts_externes['beneficiaire']["siret"] = doss['demandeur']['siret']

            if doss['demandeur']['address']['cityName'] :
                contacts_externes['beneficiaire']["adresse"] = doss['demandeur']['address']['cityName']

    return contacts_externes
