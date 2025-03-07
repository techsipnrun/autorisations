from django.shortcuts import render
from django.contrib.auth.decorators import login_required



@login_required(login_url='/login/')
def accueil(request):
    return render(request, 'instruction/instruction.html')

@login_required(login_url='/login/')
def avis(request):
    return render(request, 'instruction/avis.html')

@login_required(login_url='/login/')
def archives(request):
    return render(request, 'instruction/archives.html')