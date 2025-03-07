from django.urls import path
from . import views

urlpatterns = [
    path('', views.accueil, name='accueil_view'),
    path('avis/', views.avis, name='avis_view'),
    path('archives/', views.archives, name='archives_view'),
]