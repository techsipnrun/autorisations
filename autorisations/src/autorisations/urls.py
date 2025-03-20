from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

from . import views
from .custom_admin import custom_admin_site

# Vue de redirection explicite
def redirect_to_admin(request):
    return redirect('/bancarisation/')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('bancarisation/', custom_admin_site.urls),  # Ajoute l'admin personnalisé
    path('bancarisation/', redirect_to_admin, name='bancarisation_view'),
    path('bancarisation_guide/', views.guide_bancarisation, name='guide_bancarisation_view'), # Guide bancarisation
    path('', include('authent.urls')),
    path('', include('instruction.urls')),
    path('', include('BDD.urls')),
]
