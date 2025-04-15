if __name__ == "__main__":
    
    from normalisation.setup import init_setup

    init_setup()

    from autorisations.models.models_instruction import EtatDemarche, Demarche, ChampType, DossierType, EtatDossier, Dossier, Champ, Demande, EtatDemande, DemandeType
    from autorisations.models.models_utilisateurs import Groupeinstructeur, ContactExterne, Instructeur, DossierBeneficiaire, TypeContactExterne, DossierInterlocuteur
    from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, DossierDocument, Message, MessageDocument
    from autorisations.src.DS.call_DS import recup_data_DS
    from BDD.pg_functions import get_number_demarche_Postgres
    from synchronisation.src.functions import *
    from synchronisation.src.synchro.sync_process import synchro_process
    import logging
    from normalisation.normalize_main import normalize_process
    logger = logging.getLogger('ORM_DJANGO')

    numeros_demarche = get_number_demarche_Postgres()

    for num in numeros_demarche :
        datas_DS = recup_data_DS(num)
        resultats = normalize_process(datas_DS["demarche"])
        synchro_process(resultats)

    # Test pour une démarche
    # datas_DS = recup_data_DS(numeros_demarche[0])
    # datas_DS = recup_data_DS(114297)
    # save_to_json(resultats)
        