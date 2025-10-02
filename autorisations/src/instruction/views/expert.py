from django.utils import timezone
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from autorisations.models.models_instruction import Dossier
from autorisations.models.models_utilisateurs import Instructeur
from autorisations.models.models_documents import Document
from autorisations.models.models_avis import Avis

from django.contrib import messages
import logging


logger = logging.getLogger("ORM_DJANGO")
loggerDS = logging.getLogger("API_DS")  


@login_required(login_url='/login/')
def avis(request):
    return render(request, 'instruction/avis.html')