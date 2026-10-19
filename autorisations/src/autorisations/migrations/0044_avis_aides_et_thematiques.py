from django.db import migrations, models


SQL = """
DO $champs$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'avis' AND table_name = 'avis_formulaire_champ' AND column_name = 'placeholder') THEN
        ALTER TABLE avis.avis_formulaire_champ ADD COLUMN placeholder text NOT NULL DEFAULT '';
        UPDATE avis.avis_formulaire_champ champ
        SET placeholder = CASE WHEN config.code = 'existant' THEN 'Note libre...' ELSE 'Note libre pour le demandeur…' END
        FROM avis.avis_formulaire_configuration config
        WHERE champ.id_configuration = config.id AND champ.code = 'note_demandeur';
        UPDATE avis.avis_formulaire_champ SET placeholder = 'Ex. CS-2026-042',
            aide = CASE WHEN aide = '' THEN 'Si ce champ n’est pas rempli, l’avis se verra attribuer un numéro par défaut.' ELSE aide END
        WHERE code = 'numero_avis_externe';
    END IF;
    ALTER TABLE avis.avis_formulaire_champ ADD COLUMN IF NOT EXISTS choix_autorises jsonb NULL;
END;
$champs$;
"""


def enrichir_champs(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(SQL)


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0043_avis_formulaire_existant")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(enrichir_champs, migrations.RunPython.noop)],
        state_operations=[
            migrations.AddField(model_name="avisformulairechamp", name="placeholder", field=models.TextField(blank=True, default="")),
            migrations.AddField(model_name="avisformulairechamp", name="choix_autorises", field=models.JSONField(blank=True, null=True, default=None)),
        ],
    )]
