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


    
    path('avis/', views.avis, name='avis_view'),
    path('requetes/', views.requetes, name='requetes_view'),
]