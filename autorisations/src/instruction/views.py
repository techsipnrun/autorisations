from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required

from autorisations.models.models_documents import DocumentFormat



@login_required(login_url='/login/')
def accueil(request):
    return render(request, 'instruction/instruction.html')

@login_required(login_url='/login/')
def avis(request):
    return render(request, 'instruction/avis.html')

@login_required(login_url='/login/')
def suivi(request):

    # from django.db import connection
    # doc = DocumentFormat(id=26, format="test format")
    # doc.save()
  
    return render(request, 'instruction/suivi.html')

@login_required(login_url='/login/')
def preinstruction(request):
    return render(request, 'instruction/preinstruction.html')