from django.http import HttpResponse
from django.urls import path
from instruction.views import messagerie, preinstruction, views, instruction, changement_etape, requete, avis
from django.contrib import admin

urlpatterns = [

    # HABILITATIONS
    path("gestion_groupes/", views.gestion_groupes, name="gestion_groupes"),

    # AVIS
    path("instruction/<int:num_dossier>/ajouter_avis", avis.instruction_dossier_ajouter_avis, name="instruction_dossier_ajouter_avis"),
    path("instruction/<int:num_dossier>/avis/<int:avis_id>/edit", avis.instruction_dossier_ajouter_avis, name="instruction_dossier_ajouter_avis"),
    path("instruction/<int:num_dossier>/confirmer_ajout_avis", avis.instruction_dossier_confirmer_ajout_avis, name="instruction_dossier_confirmer_ajout_avis"),
    path("instruction/<int:num_dossier>/confirmer-avis/<int:avis_id>/",avis.instruction_dossier_confirmer_ajout_avis,name="instruction_dossier_confirmer_ajout_avis"),
    path("instruction/<int:num_dossier>/enregistrer_brouillon_avis", avis.instruction_dossier_enregistrer_brouillon_avis, name="instruction_dossier_enregistrer_brouillon_avis"),
    path("instruction/<int:num_dossier>/enregistrer_brouillon_avis/<int:avis_id>/", avis.instruction_dossier_enregistrer_brouillon_avis, name="instruction_dossier_enregistrer_brouillon_avis"),
    path("instruction/<int:num_dossier>/consultation", avis.instruction_dossier_consultation, name="instruction_dossier_consultation"),
    path("instruction/<int:num_dossier>/consultation/<int:avis_id>/", avis.instruction_dossier_avis, name="instruction_dossier_avis"),
    path("instruction/supprimer_avis", avis.supprimer_avis, name="supprimer_avis"),
    path("instruction/envoyer_message_avis/", avis.envoyer_message_avis, name="envoyer_message_avis"),
    path('message/<int:id>/supprimer_message_avis/', messagerie.supprimer_message_avis, name='supprimer_message_avis'),
    path("avis/<int:avis_id>/supprimer-doc/<str:champ>/", avis.supprimer_document_avis, name="supprimer_document_avis"),

    
    
    path('reception_avis/', views.avis, name='avis_view'),
    

    # INSTRUCTION
    path('instruction/', instruction.accueil, name='accueil_view'),
    path('instruction-demarche/<int:num_demarche>', instruction.instruction_demarche, name='instruction_demarche'),
    path('instruction/<int:num_dossier>/', instruction.instruction_dossier, name='instruction_dossier'),
    path('instruction/<int:num_dossier>/messagerie', messagerie.instruction_dossier_messagerie, name='instruction_dossier_messagerie'),
    path('passer-en-instruction/', preinstruction.passer_en_instruction, name='passer_en_instruction'),
    path('message/<int:id>/supprimer/', messagerie.supprimer_message, name='supprimer_message'),
    path('changer-valideur/', views.changer_valideur, name='changer_valideur'),
    path('changer-relecteur/', views.changer_relecteur, name='changer_relecteur'),
    path("instruction/ajouter-relecteur/", instruction.ajouter_relecteur_dossier, name="ajouter_relecteur_dossier"),
    path("instruction/relecture-faite/", instruction.relecture_faite, name="relecture_faite"),
    path("instruction/retirer-relecteur/", instruction.retirer_relecteur, name="retirer_relecteur"),
    path("email/<int:email_id>/preview/", messagerie.previsualiser_email, name="preview_email"),
    path("email/<int:email_id>/envoyer/", messagerie.envoyer_mail, name="envoyer_mail"),
    path("email/<int:email_id>/supprimer/", messagerie.supprimer_mail, name="supprimer_mail"),

    # MES DOSSIERS
    path('', instruction.mesdossiers, name='mesdossiers_view'),
    path('mesdossiers/', instruction.mesdossiers, name='mesdossiers_view'),



    # PRÉ-INSTRUCTION
    path('preinstruction/', preinstruction.preinstruction, name='preinstruction_view'),
    path('preinstruction/<int:numero>/', preinstruction.preinstruction_dossier, name='preinstruction_dossier'),
    path('preinstruction/<int:numero>/messagerie', messagerie.preinstruction_dossier_messagerie, name='preinstruction_dossier_messagerie'),
    path('preinstruction/<int:numero>/messagerie/envoyer/', messagerie.envoyer_message_dossier, name='envoyer_message_dossier'),
    path('preinstruction/declaration_manifestations/<int:numero>/', views.dossier_manif_sportive_sans_ds, name='dossier_manif_sportive_sans_ds'),
    


    # ACTUALISATION
    path("actualiser/", views.actualiser_donnees, name="actualiser_donnees"),
    path("etat-actualisation/", views.etat_actualisation, name="etat_actualisation"),
    path('instruction/<int:num_dossier>/actualiser', instruction.actualiser_dossier, name='actualiser_dossier'),
    path('instruction/<int:num_demarche>/synchroniser/', views.synchroniser_demarche, name='synchroniser_demarche'),
    path('preinstruction/<int:num_demarche>/synchroniser/', views.synchroniser_demarche_depuis_reception, name='synchroniser_demarche_depuis_reception'),
    path('preinstruction/<int:numero>/messagerie/actualiser/', messagerie.actualiser_messages, name='actualiser_messages'),



    # GROUPE INSTRUCTEUR
    path('changer-groupe-instructeur/', preinstruction.changer_groupe_instructeur, name='changer_groupe_instructeur'),
    path('instruction/se-declarer-instructeur/', views.se_declarer_instructeur, name='se_declarer_instructeur'),
    path('instruction/retirer-instructeur/', views.retirer_instructeur, name='retirer_instructeur'),


    # CARTO
    path("instruction/<int:numero_dossier>/edit_carto/<int:id_champ>/",views.edit_carto,name="edit_carto"),
    path("instruction/enregistrer-geom/", views.enregistrer_geom, name="enregistrer_geom"),


    # ANNEXE, NOTE, RELECTURE
    path('ajouter_annexe/<int:dossier_id>/', views.ajouter_annexe_dossier, name='ajouter_annexe_dossier'),
    path('supprimer_annexe/', views.supprimer_annexe_instructeur, name='supprimer_annexe_instructeur'),
    # path("annexe/<path:chemin>", views.afficher_annexe, name="afficher_annexe"),
    path('annexe/<path:chemin>/<str:titre>/', views.afficher_annexe, name='afficher_annexe'),

    path('instruction/note/', instruction.sauvegarder_note_dossier, name='sauvegarder_note_dossier'),
    # path("instruction/relecture/", instruction.mettre_a_jour_relecture, name="mettre_a_jour_relecture"),
        
    
    # REQUÊTES
    path('requetes/', requete.requete_dossiers, name='requetes_view'),
    path('autocomplete/numero/', requete.autocomplete_numero_dossier, name='autocomplete_numero_dossier'),
    path("autocomplete/nom/", requete.autocomplete_nom_beneficiaire, name="autocomplete_nom_beneficiaire"),
    path("autocomplete/instructeur/", requete.autocomplete_instructeur, name="autocomplete_instructeur"),


    # CHANGEMENT ÉTAPE
    path("changer-etape/passer-en-pre-instruction/", changement_etape.passer_en_pre_instruction, name="passer_en_pre_instruction_url"),
    path("changer-etape/demander-des-complements/", changement_etape.demander_des_complements, name="demander_des_complements_url"),
    path("changer-etape/non-soumis/", changement_etape.dossier_non_soumis_a_autorisation, name="classer_le_dossier_comme_non_soumis_a_autorisation_url"),
    path("changer-etape/refuse/", changement_etape.refuse_le_dossier, name="classer_le_dossier_comme_refuse_url"),
    path("changer-etape/passer-en-instruction/", changement_etape.passer_en_instruction, name="passer_en_instruction_url"),
    path("changer-etape/validation-avis/", changement_etape.envoyer_pour_validation_avant_demande_avis, name="envoyer_pour_validation_avant_demande_avis_url"),
    path("changer-etape/validation-signature/", changement_etape.envoyer_pour_validation_avant_signature, name="envoyer_pour_validation_avant_signature_url"),
    path("changer-etape/valider-modele-et-acte/", changement_etape.valider_le_modele_de_demande_d_avis_et_le_projet_d_acte, name="valider_le_modele_de_demande_d_avis_et_le_projet_d_acte_url"),
    path("changer-etape/avis-envoye/", changement_etape.avis_envoye, name="avis_envoye_url"),
    path("changer-etape/repasser-en-instruction/", changement_etape.repasser_en_instruction, name="repasser_en_instruction_url"),
    path("changer-etape/relecture-qualite/", changement_etape.acte_inchange_envoyer_pour_relecture_qualite, name="acte_inchange_envoyer_pour_relecture_qualite_url"),
    path("changer-etape/valider-relecture-qualite/", changement_etape.valider_et_envoyer_pour_relecture_qualite, name="valider_et_envoyer_pour_relecture_qualite_url"),
    path("changer-etape/modifs-pour-validation/", changement_etape.envoyer_les_modifications_de_l_acte_pour_validation, name="envoyer_les_modifications_de_l_acte_pour_validation_url"),
    path("changer-etape/signature/", changement_etape.envoyer_pour_signature, name="envoyer_pour_signature_url"),
    path("changer-etape/acte-envoye/", changement_etape.envoyer_l_acte, name="envoyer_l_acte_url"),
    path("changer-etape/pret-envoye/", changement_etape.acte_pret_a_etre_envoye, name="acte_pret_a_etre_envoye_url"),
    path("changer-etape/accepte/", changement_etape.classer_le_dossier_comme_accepte, name="classer_le_dossier_comme_accepte_url"),


    
]