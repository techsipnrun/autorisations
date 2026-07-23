from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("autorisations", "0021_alter_actionspossibles_options"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # La colonne et sa contrainte sont gérées directement dans PostgreSQL.
            # Cette migration synchronise uniquement l'état connu de Django.
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="dossierrelecteur",
                    name="id_demandeur_relecture",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        db_column="id_demandeur_relecture",
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="relectures_demandees",
                        to="autorisations.instructeur",
                    ),
                ),
            ],
        ),
    ]
