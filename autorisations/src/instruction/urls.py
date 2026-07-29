from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import path
from instruction.views import messagerie, preinstruction, views, instruction, changement_etape, requete, avis, expert, synchro, declaration_manifestations
from django.contrib import admin
from django.views.generic import RedirectView, TemplateView
from django.templatetags.static import static

urlpatterns = [

    # GESTION
    path("gestion_groupes/", views.gestion_groupes, name="gestion_groupes"),
    path("gestion_contacts/", views.gestion_contacts, name="gestion_contacts"),
    path("gestion_logs/", views.gestion_logs, name="gestion_logs"),


    # DOCUMENTATION
    path("docs/", lambda request: redirect(static("index.html")), name="docs"),
    

    # AVIS
    path("instruction/<int:num_dossier>/ajouter_avis", avis.instruction_dossier_ajouter_avis, name="instruction_dossier_ajouter_avis"),
    path("instruction/<int:num_dossier>/ajouter_avis_existant", avis.instruction_dossier_ajouter_avis_existant, name="instruction_dossier_ajouter_avis_existant"),
    path("instruction/<int:num_dossier>/ajouter-avis-hors-appli/", avis.ajouter_avis_hors_appli, name="ajouter_avis_hors_appli"),
    path("instruction/ajouter-pj_avis/<int:avis_id>/", avis.ajouter_pj_avis, name="ajouter_pj_avis"),
    path("instruction/<int:num_dossier>/lier-avis/<int:avis_id>/", avis.lier_dossier_avis, name="lier_dossier_avis"),
    path("avis/<int:avis_id>/pj/<int:document_id>/supprimer/", avis.supprimer_pj_avis,name="supprimer_pj_avis",),
    path("avis/<int:avis_id>/note/", avis.mettre_a_jour_note_avis, name="mettre_a_jour_note_avis"),
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
    path("avis/remplacer_document_avis/", avis.remplacer_document_avis, name="remplacer_document_avis"),


    # EXPERT
    path('reception_avis/', expert.avis, name='avis_view'),
    path("reception_avis/<int:avis_id>/", expert.avis_expert, name="avis_expert"),
    path('message/<int:id>/supprimer_message_avis_vision_expert/', messagerie.supprimer_message_avis_vision_expert, name='supprimer_message_avis_vision_expert'),
    path("instruction/envoyer_message_avis_vision_expert/", avis.envoyer_message_avis_vision_expert, name="envoyer_message_avis_vision_expert"),
    path("reception_avis/<int:avis_id>/donner_son_avis", expert.donner_son_avis, name="donner_son_avis"),
    path("remplacer-avis-signe/", expert.remplacer_avis_signe, name="remplacer_avis_signe"),
    path("deposer_avis_signe/", expert.deposer_avis_signe, name="deposer_avis_signe"),
    path("publier-raa/<int:avis_id>/", expert.publier_avis_raa, name="publier_avis_raa"),
    path("reception_avis/nouvelle_demande_avis_generique/", avis.nouvelle_demande_avis_generique, name="nouvelle_demande_avis_generique"),
    path("reception_avis/nouvelle_demande_avis_generique/confirmer/", avis.avis_confirmer_nouvelle_demande_generique, name="avis_confirmer_nouvelle_demande_generique"),
    path("enregistrer-date-transmission-cs/<int:avis_id>/", expert.enregistrer_date_transmission_cs, name="enregistrer_date_transmission_cs"),


    # INSTRUCTION
    path('instruction/', instruction.accueil, name='accueil_view'),
    path('instruction-demarche/<int:num_demarche>', instruction.instruction_demarche, name='instruction_demarche'),
    path('instruction/<int:num_dossier>/', instruction.instruction_dossier, name='instruction_dossier'),
    path('instruction/<int:num_dossier>/projets-acte/', instruction.rechercher_projets_acte, name='rechercher_projets_acte'),
    path('instruction/<int:num_dossier>/messagerie', messagerie.instruction_dossier_messagerie, name='instruction_dossier_messagerie'),
    path('message/<int:id>/supprimer/', messagerie.supprimer_message, name='supprimer_message'),
    path('changer-valideur/', views.changer_valideur, name='changer_valideur'),
    path('changer-relecteur/', views.changer_relecteur, name='changer_relecteur'),
    path('changer_intermediaire_signature/', views.changer_intermediaire_signature, name='changer_intermediaire_signature'),
    path('changer_envoyeur_acte/', views.changer_envoyeur_acte, name='changer_envoyeur_acte'),
    path('changer_publieur_raa/', views.changer_publieur_raa, name='changer_publieur_raa'),
    path("instruction/dossier-precedent/<int:num_dossier_precedent>/", views.rediriger_vers_dossier_precedent, name="rediriger_vers_dossier_precedent"),
    path("instruction/<int:num_dossier>/nom-plus-parlant/", views.update_nom_plus_parlant, name="dossier_update_nom_plus_parlant"),
    
    path("instruction/ajouter-relecteur/", instruction.ajouter_relecteur_dossier, name="ajouter_relecteur_dossier"),
    path("instruction/relecture-faite/", instruction.relecture_faite, name="relecture_faite"),
    path("instruction/retirer-relecteur/", instruction.retirer_relecteur, name="retirer_relecteur"),
    path("email/<int:email_id>/preview/", messagerie.previsualiser_email, name="preview_email"),
    path("email/<int:email_id>/envoyer/", messagerie.envoyer_mail_en_copie, name="envoyer_mail_en_copie"),
    path("email/<int:email_id>/supprimer/", messagerie.supprimer_mail, name="supprimer_mail"),


    # MES DOSSIERS
    path('', instruction.mesdossiers, name='mesdossiers_view'),
    path('mesdossiers/', instruction.mesdossiers, name='mesdossiers_view'),


    # PRÉ-INSTRUCTION
    path('preinstruction/', preinstruction.preinstruction, name='preinstruction_view'),
    path('preinstruction/<int:numero>/', preinstruction.preinstruction_dossier, name='preinstruction_dossier'),
    path('preinstruction/<int:numero>/messagerie', messagerie.preinstruction_dossier_messagerie, name='preinstruction_dossier_messagerie'),
    path('preinstruction/<int:numero>/messagerie/envoyer/', messagerie.envoyer_message_dossier, name='envoyer_message_dossier'),
    

    # ACTUALISATION
    path("actualiser/", synchro.actualiser_donnees, name="actualiser_donnees"),
    path("etat-actualisation/", synchro.etat_actualisation, name="etat_actualisation"),
    path('instruction/<int:num_dossier>/actualiser', synchro.actualiser_dossier, name='actualiser_dossier'),
    path('instruction/<int:num_demarche>/synchroniser/', synchro.synchroniser_demarche, name='synchroniser_demarche'),
    path('preinstruction/<int:num_demarche>/synchroniser/', synchro.synchroniser_demarche_depuis_reception, name='synchroniser_demarche_depuis_reception'),
    path('preinstruction/<int:numero>/messagerie/actualiser/', messagerie.actualiser_messages, name='actualiser_messages'),
    path('instruction/<int:num_dossier>/etat-actualisation/', synchro.etat_actualisation_dossier, name='etat_actualisation_dossier'),
    path("instruction/<int:num_demarche>/etat-actualisation-demarche/",synchro.etat_actualisation_demarche,name="etat_actualisation_demarche"),


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
    path('annexe/<path:chemin>/<str:titre>/', views.afficher_annexe, name='afficher_annexe'),
    path('instruction/note/', instruction.sauvegarder_note_dossier, name='sauvegarder_note_dossier'),
    path('instruction/supprimer_note/', instruction.supprimer_note_dossier, name='supprimer_note_dossier'),
        
    
    # REQUÊTES
    path('requetes/', requete.requete_dossiers, name='requetes_view'),
    path('requetes/dossiers/', requete.requete_dossiers, name='requetes_dossiers'),
    path('requetes/avis/', requete.requete_avis, name='requetes_avis'),

    path('autocomplete/numero/', requete.autocomplete_numero_dossier, name='autocomplete_numero_dossier'),
    path("autocomplete/nom/", requete.autocomplete_nom_beneficiaire, name="autocomplete_nom_beneficiaire"),
    path("autocomplete/instructeur/", requete.autocomplete_instructeur, name="autocomplete_instructeur"),
    path("autocomplete/demandeur/", requete.autocomplete_demandeur, name="autocomplete_demandeur"),
    path("autocomplete/expert/", requete.autocomplete_expert, name="autocomplete_expert"),


    # CHANGEMENT ÉTAPE
    path("changer-etape/passer-en-pre-instruction/", changement_etape.passer_en_pre_instruction, name="passer_en_pre_instruction_url"),
    path("changer-etape/demander-des-complements/", changement_etape.demander_des_complements, name="demander_des_complements_url"),
    path("changer-etape/non-soumis/", changement_etape.dossier_non_soumis_a_autorisation, name="classer_le_dossier_comme_non_soumis_a_autorisation_url"),
    path("changer-etape/refuse/", changement_etape.classer_le_dossier_comme_refuse, name="classer_le_dossier_comme_refuse_url"),
    path("changer-etape/passer-en-instruction/", changement_etape.passer_en_instruction, name="passer_en_instruction_url"),
    path("changer-etape/validation-avis/", changement_etape.faire_valider_une_demande_d_avis, name="faire_valider_une_demande_d_avis_url"),
    path("changer-etape/validation-signature/", changement_etape.faire_valider_le_projet_d_acte, name="faire_valider_le_projet_d_acte_url"),
    path("changer-etape/valider-modele-et-acte/", changement_etape.valider_le_modele_de_demande_d_avis_et_le_projet_d_acte, name="valider_le_modele_de_demande_d_avis_et_le_projet_d_acte_url"),
    path("changer-etape/avis-envoye/", changement_etape.avis_envoye, name="avis_envoye_url"),
    path("changer-etape/repasser-en-instruction/", changement_etape.repasser_en_instruction, name="repasser_en_instruction_url"),
    path("changer-etape/relecture-qualite/", changement_etape.acte_inchange_envoyer_pour_relecture_qualite, name="acte_inchange_envoyer_pour_relecture_qualite_url"),
    path("changer-etape/valider-relecture-qualite/", changement_etape.valider_et_envoyer_pour_relecture_qualite, name="valider_et_envoyer_pour_relecture_qualite_url"),
    path("changer-etape/modifs-pour-validation/", changement_etape.envoyer_les_modifications_de_l_acte_pour_validation, name="envoyer_les_modifications_de_l_acte_pour_validation_url"),
    path("changer-etape/signature/", changement_etape.pret_a_la_signature, name="pret_a_la_signature_url"),
    path("changer-etape/signature_sppn/", changement_etape.acte_pret_a_la_signature, name="acte_pret_a_la_signature_url"),
    path("changer-etape/acte-envoye/", changement_etape.envoyer_l_acte, name="envoyer_l_acte_url"),
    path("changer-etape/acte-refus-envoye/", changement_etape.envoyer_l_acte_de_refus, name="envoyer_l_acte_de_refus_url"),
    path("changer-etape/pret-envoye/", changement_etape.acte_pret_a_etre_envoye, name="acte_pret_a_etre_envoye_url"),
    path("changer-etape/remplacer-acte-signe/", changement_etape.remplacer_acte_signe, name="remplacer_acte_signe_url"),
    path("changer-etape/remplacer-numero-projet-acte/", changement_etape.remplacer_numero_projet_acte, name="remplacer_numero_projet_acte_url"),
    path("changer-etape/accepte/", changement_etape.classer_le_dossier_comme_accepte, name="classer_le_dossier_comme_accepte_url"),


    # MANIF SPORTIVE
    path('preinstruction/declaration_manifestations/<int:numero>/', declaration_manifestations.dossier_manif_sportive_sans_ds, name='dossier_manif_sportive_sans_ds'),
    path("manif-sportive/lier-dn/",declaration_manifestations.lier_dossier_manif_sportive_a_DN,name="lier_dossier_manif_sportive_a_DN"),
    path("changer-etape/accepte-declaration-manifestations/", declaration_manifestations.declaration_manifestations_accepter, name="declaration_manifestations_accepter_url"),
    path("changer-etape/refuse-declaration-manifestations/", declaration_manifestations.declaration_manifestations_refuser, name="declaration_manifestations_refuser_url"),
    path("changer-etape/non-soumis-declaration-manifestations/", declaration_manifestations.declaration_manifestations_non_soumis, name="declaration_manifestations_non_soumis_url"),
    path("changer-etape/non-repondu-declaration-manifestations/", declaration_manifestations.declaration_manifestations_non_repondu, name="declaration_manifestations_non_repondu_url"),
    path('instruction/declaration_manifestations/<int:numero>/', declaration_manifestations.dossier_manif_sportive_sans_ds, name='dossier_manif_sportive_sans_ds_archive'),
    path("manif-sportive/lier-dn-archive/",declaration_manifestations.archive_lier_dossier_manif_sportive_a_DN, name="lier_dossier_archive_manif_sportive_a_DN"),
    path("manif-sportive/ajouter_annexe/<int:id_dm>/", declaration_manifestations.ajouter_annexe_sur_DM, name="ajouter_annexe_sur_DM"),
    path("manif-sportive/email/<int:email_id>/envoyer/", messagerie.renvoyer_mail_relance, name="renvoyer_mail_relance"),
    path("manif-sportive/<int:id_dm>/relance-mail/",messagerie.envoi_manuel_mail_relance,name="envoi_manuel_mail_relance"),




]
