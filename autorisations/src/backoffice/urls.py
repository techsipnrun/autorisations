"""Routes historiques du Back Office, sans namespace supplémentaire."""
from django.urls import path

from backoffice.views import accueil, avis, cartographie, demarches, nom_dossier, services, types_actes


urlpatterns = [
    path("back-office/", accueil.back_office, name="back_office"),
    path("back-office/avis/formulaires/<slug:contexte>/", avis.configurer_formulaire, name="back_office_avis_formulaire"),
    path("back-office/avis/thematiques/", avis.configurer_thematiques, name="back_office_avis_thematiques"),
    path("back-office/cartographie/", cartographie.catalogue, name="back_office_cartographie"),
    path("back-office/cartographie/convertir/", cartographie.convertir_source, name="back_office_cartographie_convertir"),
    path("back-office/cartographie/source/", cartographie.enregistrer_source, name="back_office_cartographie_ajouter_source"),
    path("back-office/cartographie/source/<int:source_id>/", cartographie.enregistrer_source, name="back_office_cartographie_source"),
    path("back-office/cartographie/source/<int:source_id>/supprimer/", cartographie.supprimer_source, name="back_office_cartographie_supprimer_source"),
    path("back-office/cartographie/carte/<slug:code>/", cartographie.enregistrer_configuration, name="back_office_cartographie_carte"),
    path("back-office/types-actes/<int:type_id>/", types_actes.enregistrer_type_acte, name="back_office_enregistrer_type_acte"),
    path("back-office/types-actes/<int:type_id>/ordre/", types_actes.deplacer_type_acte, name="back_office_deplacer_type_acte"),
    path("back-office/demarche/<int:demarche_id>/noms/", nom_dossier.enregistrer_regles_nom_dossier, name="back_office_enregistrer_noms"),
    path("back-office/demarche/<int:demarche_id>/noms/apercu/", nom_dossier.previsualiser_nom_dossier, name="back_office_apercu_nom"),
    path("back-office/demarche/<int:demarche_id>/noms/recalculer/", nom_dossier.recalculer_noms_dossiers, name="back_office_recalculer_noms"),
    path("back-office/demarche/<int:demarche_id>/noms/numeros/", nom_dossier.autocomplete_numeros_dossiers, name="back_office_autocomplete_numeros_noms"),
    path("back-office/demarche/<int:demarche_id>/date-activite/", demarches.back_office_enregistrer_date_activite, name="back_office_enregistrer_date_activite"),
    path("back-office/demarche/<int:demarche_id>/personnalisation-tableau/", demarches.back_office_enregistrer_personnalisation_tableau, name="back_office_enregistrer_personnalisation_tableau"),
    path("back-office/services-status/", services.back_office_services_status, name="back_office_services_status"),
]
