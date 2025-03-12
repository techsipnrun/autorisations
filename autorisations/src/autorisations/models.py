from .models.models_documents import *
from .models.models_instruction import *
from .models.models_utilisateurs import *
from .models.models_avis import *


from django.contrib.auth.models import AbstractUser
from django.db import models

class CustomUser(AbstractUser):  # Étend le modèle utilisateur par défaut
    ROLE_CHOICES = [
        ('lecture_avis', 'Lecture Avis'),
    ]
    # role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='lecture_avis')

    def __str__(self):
        return f"{self.username} - {self.role}"
