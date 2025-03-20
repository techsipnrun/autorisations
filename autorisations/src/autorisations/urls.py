from django.contrib import admin
from django.urls import include, path
from .custom_admin import custom_admin_site


urlpatterns = [
    path('admin/', admin.site.urls),
    path('bancarisation/', custom_admin_site.urls),  # Ajoute l'admin personnalisé
    path('', include('authent.urls')),
    path('', include('instruction.urls')),
    path('', include('BDD.urls')),
]
