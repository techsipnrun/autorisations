import os
from django.urls import path, re_path,include
from dotenv import load_dotenv
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from django.contrib.auth import views as auth_views
from BDD.views import swagger_logout_view

from rest_framework.routers import DefaultRouter

from autorisations.settings import BASE_DIR
from .api_views import avis_views,documents_views,utilisateurs_views, instruction_views
from rest_framework.authtoken.views import obtain_auth_token

# Chemin du fichier .env en fonction de l'environnement
ENVIRONMENT = os.getenv("DJANGO_ENV", "dev")  # dev par défaut, DJANGO_ENV=prod python manage.py runserver pour lancer en prod
dotenv_path = BASE_DIR / f".env.{ENVIRONMENT}"
load_dotenv(dotenv_path)

router = DefaultRouter()

# Avis
router.register(r'avis_nature', avis_views.AvisNatureViewSet)
router.register(r'avis_thematique', avis_views.AvisThematiqueViewSet)
router.register(r'expert', avis_views.ExpertViewSet)
router.register(r'avis', avis_views.AvisViewSet)
router.register(r'avis_document', avis_views.AvisDocumentViewSet)
router.register(r'demande_avis', avis_views.DemandeAvisViewSet)

# Documents
router.register(r'document_format', documents_views.DocumentFormatViewSet)
router.register(r'document_nature', documents_views.DocumentNatureViewSet)
router.register(r'document', documents_views.DocumentViewSet)
router.register(r'dossier_document', documents_views.DossierDocumentViewSet)
router.register(r'message_document', documents_views.MessageDocumentViewSet)

# Utilisateurs
router.register(r'agent_autorisations', utilisateurs_views.AgentAutorisationsViewSet)
router.register(r'type_contact_externe', utilisateurs_views.TypeContactExterneViewSet)
router.register(r'contact_externe', utilisateurs_views.ContactExterneViewSet)
router.register(r'dossier_interlocuteur', utilisateurs_views.DossierInterlocuteurViewSet)
router.register(r'dossier_beneficiaire', utilisateurs_views.DossierBeneficiaireViewSet)
router.register(r'instructeur', utilisateurs_views.InstructeurViewSet)
router.register(r'groupeinstructeur', utilisateurs_views.GroupeinstructeurViewSet)
router.register(r'groupeinstructeur_demarche', utilisateurs_views.GroupeinstructeurDemarcheViewSet)
router.register(r'groupeinstructeur_instructeur', utilisateurs_views.GroupeinstructeurInstructeurViewSet)
router.register(r'dossier_instructeur', utilisateurs_views.DossierInstructeurViewSet)

# Instruction
router.register(r'champ_type', instruction_views.ChampTypeViewSet)
router.register(r'etat_demande', instruction_views.EtatDemandeViewSet)
router.register(r'etat_demarche', instruction_views.EtatDemarcheViewSet)
router.register(r'etat_dossier', instruction_views.EtatDossierViewSet)
router.register(r'priorite', instruction_views.PrioriteViewSet)
router.register(r'demande_type', instruction_views.DemandeTypeViewSet)
router.register(r'groupe', instruction_views.GroupeViewSet)
router.register(r'demarche', instruction_views.DemarcheViewSet)
router.register(r'dossier_type', instruction_views.DossierTypeViewSet)
router.register(r'dossier', instruction_views.DossierViewSet)
router.register(r'demande', instruction_views.DemandeViewSet)
router.register(r'champ', instruction_views.ChampViewSet)
router.register(r'demande_champ', instruction_views.DemandeChampViewSet)
router.register(r'message', instruction_views.MessageViewSet)
router.register(r'dossier_groupe', instruction_views.DossierGroupeViewSet)

schema_view = get_schema_view(
   openapi.Info(
      title="API Autorisations",
      default_version='v1',
      description="Cette API permet d'interragir facilement avec les données propres aux demandes d'autorisations.",
      contact=openapi.Contact(email="louis.calu@reunion-parcnational.fr"),
      # license=openapi.License(name="BSD License"),
   ),
   public=True,  #True = API visible dans le Swagger même si le user n'a pas le droit de l'utiliser.
   permission_classes=(permissions.AllowAny,),
)



urlpatterns = [
   path('swagger.<format>/', schema_view.without_ui(cache_timeout=0), name='schema-json'),
   path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
   path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

   path('swagger/logout/', swagger_logout_view, name='swagger_logout'),
   path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='swagger_login'),
 
   path(f"{os.environ.get('API_PG_URL')}", include(router.urls)),
   path(f"{os.environ.get('API_PG_URL')}token/", obtain_auth_token, name='api_token_auth'),  # Endpoint pour obtenir un token
]