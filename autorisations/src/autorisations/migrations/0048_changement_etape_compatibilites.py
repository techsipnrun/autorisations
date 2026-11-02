from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0047_actions_priorites")]
    # Fonctionnalité retirée. Numéro conservé pour les installations qui ont
    # déjà enregistré cette migration déclarative ; aucun état ni SQL à ajouter.
    operations = []
