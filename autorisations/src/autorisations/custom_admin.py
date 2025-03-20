from django.contrib import admin
from .models.models_avis import Avis, AvisDocument, Expert
from .models.models_documents import Document, DossierDocument
from .models.models_instruction import Dossier, Demande, DossierGroupe, Groupe
from .models.models_utilisateurs import ContactExterne, DossierInstructeur, DemandeInterlocuteur, DemandeBeneficiaire, Instructeur


class CustomAdminSite(admin.AdminSite):
    site_header = "Bancarisation des Autorisations"
    index_title = "Portail de bancararisation"

    def get_app_list(self, request):
        """
        Personnalise l'ordre des modèles dans l'interface admin.
        """
        app_list = super().get_app_list(request)

        # Définition d'un ordre précis des modèles
        desired_order = [
            "Dossier", "Demande", "Document",
            "DossierDocument", "Instructeur", "DossierInstructeur", "ContactExterne",
            "Expert", "Avis", "AvisDocument",
            "DemandeInterlocuteur", "DemandeBeneficiaire", "Groupe", "DossierGroupe",
        ]

        for app in app_list:
            app["models"].sort(
                key=lambda x: desired_order.index(x["object_name"]) if x["object_name"] in desired_order else len(desired_order)
            )

        return app_list

# Instancier le site admin personnalisé
custom_admin_site = CustomAdminSite(name="custom_admin")

custom_admin_site.register(Dossier)
custom_admin_site.register(Demande)
custom_admin_site.register(Document)
custom_admin_site.register(DossierDocument)
custom_admin_site.register(Instructeur)
custom_admin_site.register(DossierInstructeur)
custom_admin_site.register(ContactExterne)
custom_admin_site.register(Expert)
custom_admin_site.register(Avis)
custom_admin_site.register(AvisDocument)
custom_admin_site.register(Groupe)
custom_admin_site.register(DossierGroupe)
custom_admin_site.register(DemandeInterlocuteur)
custom_admin_site.register(DemandeBeneficiaire)
