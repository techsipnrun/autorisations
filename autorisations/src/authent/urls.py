from django.shortcuts import redirect
from django.urls import path
from django.contrib.auth import views as auth_views

# from instruction import views


urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='logout.html'), name='logout')
]