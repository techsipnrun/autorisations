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

    if not contacts_externes :
        contacts_externes = {
            'beneficiaire': {},
            'demandeur_intermediaire': {},
            'demandeur_pers_morale': {}
        }


    # --------------------------------------------------------------------------------
    # Démarche à destination d'une personne physique, avec un demandeur intermédiaire
    # --------------------------------------------------------------------------------
    if doss.get("prenomMandataire") and doss.get("nomMandataire"):
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

    else:
        # -------------------------------------------------------------------
        #  Demandeur = Personne Physique sans demandeur intermédiaire déclaré
        # -------------------------------------------------------------------
        if doss['demandeur']['__typename'] == 'PersonnePhysique' :
            contacts_externes['beneficiaire']["email"] = clean_email(doss['usager']['email'])
            contacts_externes['beneficiaire']["id_type"] = id_type_beneficiaire
            contacts_externes['beneficiaire']["nom"] = clean_surname(doss['demandeur']['nom'])
            contacts_externes['beneficiaire']["prenom"] = clean_name(doss['demandeur']['prenom'])



        # -----------------------------------------------------------------------------------------------------
        #  Demandeur = Personne Morale (pas la possibilité de mettre de demandeur intermédiaire de toute façon)
        #  ---
        #  ATTENTION : Si le remplisseur du form = Pers Morale --> Ce n'est pas forcément le bénéficiaire (il peut servir de demandeur intermédiaire)
        #  On stocke dans un contacts_externes['demandeur_pers_morale'] et décider seulement dans norma_dossier_champs si on le passe en ['beneficiaire'] ou ['demandeur_intermediaire']
        # -----------------------------------------------------------------------------------------------------
        if doss['demandeur']['__typename'] == 'PersonneMorale' :

            raison_sociale = doss['demandeur']['entreprise']['raisonSociale'] if doss['demandeur'].get('entreprise') else None
            orga = doss['demandeur']['entreprise']['nom'] if doss['demandeur'].get('entreprise') else (doss['demandeur']['association']['titre'] if doss['demandeur'].get('association') else None)

            if raison_sociale :
                contacts_externes['demandeur_pers_morale']["raison_sociale"] = raison_sociale
                
            if orga :
                contacts_externes['demandeur_pers_morale']["organisation"] = orga

            if not raison_sociale and not orga :
                contacts_externes['demandeur_pers_morale']["raison_sociale"] = doss['demandeur']['entreprise']['libelleNaf'] if doss['demandeur'].get('entreprise') else None

            contacts_externes['demandeur_pers_morale']["email"] = clean_email(doss['usager']['email'])

            if doss['demandeur']['siret'] :
                contacts_externes['demandeur_pers_morale']["siret"] = doss['demandeur']['siret']

            if doss['demandeur']['address']['cityName'] :
                contacts_externes['demandeur_pers_morale']["adresse"] = doss['demandeur']['address']['cityName']


    return contacts_externes
