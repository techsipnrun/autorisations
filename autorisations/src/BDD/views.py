from django.shortcuts import render, redirect
from django.contrib.auth import logout, login

# Create your views here.

def swagger_logout_view(request):
    """Déconnexion spécifique pour Swagger via GET."""
    logout(request)
    return redirect('/swagger/')  # Redirige vers Swagger
