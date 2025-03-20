from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required


@login_required(login_url='/login/')
def guide_bancarisation(request):
    return render(request, 'autorisations/guide_bancarisation.html')
