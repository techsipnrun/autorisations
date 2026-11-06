from django.urls import path
from . import views, history_views, number_views

app_name = "document_generation"
urlpatterns = [
    path('dossier/<int:num_dossier>/historique/actes/verifier/', history_views.act_status, name='act_history_status'),
    path('dossier/<int:num_dossier>/template/<int:template_id>/numeros/', number_views.choices, name='number_choices'),
    path('dossier/<int:num_dossier>/template/<int:template_id>/numero/', number_views.select, name='number_select'),
    path('dossier/<int:num_dossier>/historique/verifier/', history_views.status, name='history_status'),
    path('dossier/<int:num_dossier>/generation/<int:generation_id>/fichiers/', history_views.choices, name='history_choices'),
    path('dossier/<int:num_dossier>/generation/<int:generation_id>/supprimer/', history_views.remove, name='history_remove'),
    path('dossier/<int:num_dossier>/generation/<int:generation_id>/associer/', history_views.relink, name='history_relink'),
    path('dossier/<int:num_dossier>/generation/<int:generation_id>/telecharger/', views.download_generated, name='download_generated'),
    path("dossier/<int:num_dossier>/", views.dossier_generation, name="dossier_generation"),
    path("preview/<int:num_dossier>/<int:template_id>/", views.preview_pdf, name="preview_pdf"),
    path("dossier/<int:num_dossier>/template/<int:template_id>/", views.generer_document, name="generer_document"),
]
