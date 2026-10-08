from django.core.validators import RegexValidator
from django.db import migrations, models


SQL = """
DO $migration$
DECLARE
    ajout_numero boolean := false;
    ajout_fichier boolean := false;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'documents' AND table_name = 'document_nature'
          AND column_name = 'prefixe_numero'
    ) THEN
        ALTER TABLE documents.document_nature
            ADD COLUMN prefixe_numero varchar(50) NOT NULL DEFAULT '';
        ajout_numero := true;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'documents' AND table_name = 'document_nature'
          AND column_name = 'prefixe_nom_fichier'
    ) THEN
        ALTER TABLE documents.document_nature
            ADD COLUMN prefixe_nom_fichier varchar(50) NOT NULL DEFAULT '';
        ajout_fichier := true;
    END IF;

    -- Initialiser seulement lors de la création des colonnes : une relance
    -- ne doit pas écraser une personnalisation, même un préfixe laissé vide.
    IF ajout_numero THEN
        UPDATE documents.document_nature AS n
        SET prefixe_numero = p.prefixe
        FROM (VALUES
            ('Arrêté directeur', 'DIR-I-'),
            ('Déliberation CA', 'CA/'),
            ('Avis simple', 'AVIS-SIMPLE-'),
            ('Avis conforme', 'AVIS-CONFORME-')
        ) AS p(nature, prefixe)
        WHERE n.nature = p.nature;
    END IF;
    IF ajout_fichier THEN
        UPDATE documents.document_nature AS n
        SET prefixe_nom_fichier = p.prefixe
        FROM (VALUES
            ('Arrêté directeur', 'DIR-I-'),
            ('Déliberation CA', 'DELIB-CA-'),
            ('Avis simple', 'AVIS-SIMPLE-'),
            ('Avis conforme', 'AVIS-CONFORME-')
        ) AS p(nature, prefixe)
        WHERE n.nature = p.nature;
    END IF;
END;
$migration$;
"""


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0036_nom_dossier_transformations_personnalisees")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop)],
        state_operations=[
            migrations.AddField(
                model_name="documentnature", name="prefixe_numero",
                field=models.CharField(
                    max_length=50, blank=True, default="", verbose_name="Préfixe du numéro",
                    help_text="Préfixe affiché dans l’application, séparateur inclus (ex. DIR-I- ou CA/).",
                ),
            ),
            migrations.AddField(
                model_name="documentnature", name="prefixe_nom_fichier",
                field=models.CharField(
                    max_length=50, blank=True, default="", verbose_name="Préfixe du nom de fichier",
                    help_text="Préfixe des nouveaux fichiers signés, séparateur inclus (ex. DELIB-CA-).",
                    validators=[RegexValidator(
                        regex=r'[\\/:*?"<>|\x00-\x1f]', inverse_match=True,
                        message="Le préfixe ne doit pas contenir de caractère interdit dans un nom de fichier.",
                    )],
                ),
            ),
        ],
    )]
