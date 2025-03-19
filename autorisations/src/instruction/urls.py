from django.urls import path
from . import views

urlpatterns = [
    path('', views.accueil, name='accueil_view'),
    path('avis/', views.avis, name='avis_view'),
    path('suivi/', views.suivi, name='suivi_view'),
    path('preinstruction/', views.preinstruction, name='preinstruction_view'),
]