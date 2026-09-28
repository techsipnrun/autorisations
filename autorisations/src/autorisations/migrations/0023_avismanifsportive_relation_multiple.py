from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("autorisations", "0022_dossierrelecteur_demandeur_relecture"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # La table, non gérée par Django, autorise déjà plusieurs avis par
            # dossier DM. Aucun SQL ni aucune modification de donnée à jouer.
            database_operations=[],
            state_operations=[
                migrations.AlterField(
                    model_name="avismanifsportive",
                    name="id_dossier_manif_sportive",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        db_column="id_dossier_manif_sportive",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="avis",
                        to="autorisations.dossiermanifsportive",
                    ),
                ),
            ],
        ),
    ]
