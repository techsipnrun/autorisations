from django.urls import path
from . import views

urlpatterns = [
    path('', views.accueil, name='accueil_view'),
    path('avis/', views.avis, name='avis_view'),
    path('suivi/', views.suivi, name='suivi_view'),
    path('preinstruction/', views.preinstruction, name='preinstruction_view'),
    path('preinstruction/<int:numero>/', views.preinstruction_dossier, name='preinstruction_dossier'),
    path('preinstruction/<int:numero>/messagerie', views.preinstruction_dossier_messagerie, name='preinstruction_dossier_messagerie'),
    path('preinstruction/<int:numero>/messagerie/envoyer/', views.envoyer_message_dossier, name='envoyer_message_dossier'),
    path('instruction/', views.accueil, name='accueil_view'),
    path("actualiser/", views.actualiser_donnees, name="actualiser_donnees"),
    path("etat-actualisation/", views.etat_actualisation, name="etat_actualisation"),

]