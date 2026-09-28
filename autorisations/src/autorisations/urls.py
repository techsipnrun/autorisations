from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from . import views
from .custom_admin import custom_admin_site
from instruction.views import errors

handler404 = "instruction.views.errors.erreur_404"

# Vue de redirection explicite
def redirect_to_admin(request):
    return redirect('/bancarisation/')

urlpatterns = [
    path('admin/', admin.site.urls, name='admin'),
    path('bancarisation/', custom_admin_site.urls),  # Ajoute l'admin personnalisé
    path('bancarisation/', redirect_to_admin, name='bancarisation_view'),
    path('bancarisation_guide/', views.guide_bancarisation, name='guide_bancarisation_view'), # Guide bancarisation
    path('', include('authent.urls')),
    path('', include('instruction.urls')),
    path('', include('BDD.urls')),
    path("favicon.ico", RedirectView.as_view(url="/static/instruction/img/favicon.ico", permanent=True),),
    # Ce dernier motif permet d'utiliser notre page 404 également avec DEBUG=True, lorsque le handler404 de Django n'est normalement pas rendu.
    re_path(r"^.*$", errors.erreur_404, name="page_introuvable"),
]
