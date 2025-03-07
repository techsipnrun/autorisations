from django.shortcuts import redirect
from django.urls import path
from django.contrib.auth import views as auth_views


urlpatterns = [
    # Redirection pour l'URL vide vers la page de connexion
    # path('', lambda request: redirect('login'), name='home'),
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='logout.html'), name='logout')
]