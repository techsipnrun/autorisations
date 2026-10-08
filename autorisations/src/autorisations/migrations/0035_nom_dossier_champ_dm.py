from django.db import migrations, models


SQL = """
DO $migration$
DECLARE
    contrainte_type text;
BEGIN
IF to_regclass('instruction.demarche_nom_dossier_element') IS NOT NULL THEN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'instruction' AND table_name = 'demarche_nom_dossier_element'
          AND column_name = 'champ_dm'
    ) THEN
        ALTER TABLE instruction.demarche_nom_dossier_element
            ADD COLUMN champ_dm varchar(100) NULL;
    END IF;

    SELECT conname INTO contrainte_type
    FROM pg_constraint
    WHERE conrelid = 'instruction.demarche_nom_dossier_element'::regclass
      AND contype = 'c'
      AND conname <> 'demarche_nom_dossier_element_source_check'
      AND pg_get_constraintdef(oid) LIKE '%type_element%'
    LIMIT 1;
    IF contrainte_type IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE instruction.demarche_nom_dossier_element DROP CONSTRAINT %I',
            contrainte_type
        );
    END IF;
    ALTER TABLE instruction.demarche_nom_dossier_element
        ADD CONSTRAINT demarche_nom_dossier_element_type_check
        CHECK (type_element IN ('texte', 'champ_dn', 'champ_dm', 'attribut'));

    ALTER TABLE instruction.demarche_nom_dossier_element
        DROP CONSTRAINT IF EXISTS demarche_nom_dossier_element_source_check;
    ALTER TABLE instruction.demarche_nom_dossier_element
        ADD CONSTRAINT demarche_nom_dossier_element_source_check CHECK (
            (type_element = 'texte' AND texte IS NOT NULL AND id_champ IS NULL AND champ_dm IS NULL AND attribut IS NULL AND transformation = 'aucune') OR
            (type_element = 'champ_dn' AND texte IS NULL AND id_champ IS NOT NULL AND champ_dm IS NULL AND attribut IS NULL) OR
            (type_element = 'champ_dm' AND texte IS NULL AND id_champ IS NULL AND champ_dm IS NOT NULL AND attribut IS NULL) OR
            (type_element = 'attribut' AND texte IS NULL AND id_champ IS NULL AND champ_dm IS NULL AND attribut IS NOT NULL)
        );
END IF;
END;
$migration$;
"""


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0034_noms_dossiers")]

    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop)],
        state_operations=[
            migrations.AddField(
                model_name="demarchenomdossierelement",
                name="champ_dm",
                field=models.CharField(blank=True, max_length=100, null=True),
            ),
            migrations.AlterField(
                model_name="demarchenomdossierelement",
                name="type_element",
                field=models.CharField(
                    max_length=20,
                    choices=[
                        ("texte", "Texte fixe"), ("champ_dn", "Champ DN"),
                        ("champ_dm", "Champ DM"), ("attribut", "Donnée AGIDA"),
                    ],
                ),
            ),
        ],
    )]
