from django.db import migrations, models


SQL = """
DO $raccourci$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'utilisateurs' AND table_name = 'contact_externe'
          AND column_name = 'raison_sociale_raccourci'
    ) THEN
        ALTER TABLE utilisateurs.contact_externe
            ADD COLUMN raison_sociale_raccourci varchar(255) NOT NULL DEFAULT '';
    END IF;
END;
$raccourci$;
"""


def ajouter_raccourci(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0045_actes_numerotation_manuelle")]
    operations = [migrations.SeparateDatabaseAndState(
        # Le schéma PostgreSQL est administré exclusivement via sql/0046_contact_raison_sociale_raccourci.sql.
        database_operations=[],
        state_operations=[migrations.AddField(
            model_name="contactexterne", name="raison_sociale_raccourci",
            field=models.CharField(max_length=255, blank=True, default=""),
        )],
    )]
