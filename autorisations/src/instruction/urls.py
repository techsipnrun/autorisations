from django.urls import path
from instruction.views import messagerie, preinstruction, views, instruction

urlpatterns = [
    path('', instruction.accueil, name='accueil_view'),
    path('instruction/', instruction.accueil, name='accueil_view'),
    path('instruction-demarche/<int:num_demarche>', instruction.instruction_demarche, name='instruction_demarche'),
    path('instruction/<int:num_dossier>', instruction.instruction_dossier, name='instruction_dossier'),
    path('instruction/<int:num_dossier>/actualiser', instruction.actualiser_dossier, name='actualiser_dossier'),
    path('instruction/<int:num_dossier>/messagerie', messagerie.instruction_dossier_messagerie, name='instruction_dossier_messagerie'),
    path("instruction/<int:num_dossier>/consultation", instruction.instruction_dossier_consultation, name="instruction_dossier_consultation"),


    path('preinstruction/', preinstruction.preinstruction, name='preinstruction_view'),
    path('preinstruction/<int:numero>/', preinstruction.preinstruction_dossier, name='preinstruction_dossier'),
    path('preinstruction/<int:numero>/messagerie', messagerie.preinstruction_dossier_messagerie, name='preinstruction_dossier_messagerie'),
    path('preinstruction/<int:numero>/messagerie/envoyer/', messagerie.envoyer_message_dossier, name='envoyer_message_dossier'),
    path('preinstruction/<int:numero>/messagerie/actualiser/', messagerie.actualiser_messages, name='actualiser_messages'),

    path('message/<int:id>/supprimer/', messagerie.supprimer_message, name='supprimer_message'),
    path("actualiser/", views.actualiser_donnees, name="actualiser_donnees"),
    path("etat-actualisation/", views.etat_actualisation, name="etat_actualisation"),
    path('changer-etape-dossier/', views.changer_etape_dossier, name='changer_etape_dossier'),
    path('changer-groupe-instructeur/', preinstruction.changer_groupe_instructeur, name='changer_groupe_instructeur'),
    path('passer-en-instruction/', preinstruction.passer_en_instruction, name='passer_en_instruction'),
    path('passer_etape_en_preinstruction/', preinstruction.passer_etape_en_preinstruction, name='passer_etape_en_preinstruction'),
    path('preinstruction/note/', preinstruction.sauvegarder_note_dossier, name='sauvegarder_note_dossier'),
    path('instruction/se-declarer-instructeur/', views.se_declarer_instructeur, name='se_declarer_instructeur'),
    path('instruction/retirer-instructeur/', views.retirer_instructeur, name='retirer_instructeur'),
    # path("instruction/<int:numero_dossier>/edit_carto", views.edit_carto, name="edit_carto"),
    path("instruction/<int:numero_dossier>/edit_carto/<int:id_champ>/",views.edit_carto,name="edit_carto"),
    path("instruction/enregistrer-geom/", views.enregistrer_geom, name="enregistrer_geom"),

    # path('instruction/<str:numero_dossier>/champ/<int:id_champ>/edit_carto/', views.edit_carto_champ, name='edit_carto_champ'),
    # path('instruction/enregistrer_geom_champ/', views.enregistrer_geom_champ, name='enregistrer_geom_champ'),
    
    path('ajouter_annexe/<int:dossier_id>/', views.ajouter_annexe_dossier, name='ajouter_annexe_dossier'),
    path('instruction/<int:num_demarche>/synchroniser/', views.synchroniser_demarche, name='synchroniser_demarche'),






    path('carto_test/', views.carto_test, name='carto_test'),  #url de Test
    path('avis/', views.avis, name='avis_view'),
    path('requetes/', views.requetes, name='requetes_view'),
]