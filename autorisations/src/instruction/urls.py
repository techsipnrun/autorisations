from django.urls import path
# from . import views
from instruction.views import accueil, messagerie, preinstruction, views

urlpatterns = [
    path('', accueil.accueil, name='accueil_view'),
    path('instruction/', accueil.accueil, name='accueil_view'),
    path('avis/', views.avis, name='avis_view'),
    path('suivi/', views.suivi, name='suivi_view'),

    path('preinstruction/', preinstruction.preinstruction, name='preinstruction_view'),
    path('preinstruction/<int:numero>/', preinstruction.preinstruction_dossier, name='preinstruction_dossier'),
    path('preinstruction/<int:numero>/messagerie', messagerie.preinstruction_dossier_messagerie, name='preinstruction_dossier_messagerie'),
    path('preinstruction/<int:numero>/messagerie/envoyer/', messagerie.envoyer_message_dossier, name='envoyer_message_dossier'),
    path('preinstruction/<int:numero>/messagerie/actualiser/', messagerie.actualiser_messages, name='actualiser_messages'),

    path('message/<int:id>/supprimer/', messagerie.supprimer_message, name='supprimer_message'),
    path("actualiser/", views.actualiser_donnees, name="actualiser_donnees"),
    path("etat-actualisation/", views.etat_actualisation, name="etat_actualisation"),
    path('changer-groupe-instructeur/', preinstruction.changer_groupe_instructeur, name='changer_groupe_instructeur'),
]