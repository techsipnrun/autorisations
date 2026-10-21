from django.db import migrations, models


SQL = """
DO $migration$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'documents' AND table_name = 'document_nature' AND column_name = 'est_acte') THEN
        ALTER TABLE documents.document_nature ADD COLUMN est_acte boolean NOT NULL DEFAULT false;
        UPDATE documents.document_nature SET est_acte = true WHERE nature IN ('Arrêté directeur', 'Déliberation CA', 'Avis simple', 'Avis conforme');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'documents' AND table_name = 'document_nature' AND column_name = 'actif') THEN
        ALTER TABLE documents.document_nature ADD COLUMN actif boolean NOT NULL DEFAULT true;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'documents' AND table_name = 'document_nature' AND column_name = 'ordre_affichage') THEN
        ALTER TABLE documents.document_nature ADD COLUMN ordre_affichage smallint NOT NULL DEFAULT 0 CHECK (ordre_affichage >= 0);
        UPDATE documents.document_nature SET ordre_affichage = p.ordre FROM (VALUES ('Arrêté directeur', 10), ('Déliberation CA', 20), ('Avis simple', 30), ('Avis conforme', 40)) AS p(nature, ordre) WHERE document_nature.nature = p.nature;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'documents' AND table_name = 'document_nature' AND column_name = 'circuit_signature') THEN
        ALTER TABLE documents.document_nature ADD COLUMN circuit_signature varchar(20) NOT NULL DEFAULT 'direction' CHECK (circuit_signature IN ('direction', 'ca'));
        UPDATE documents.document_nature SET circuit_signature = 'ca' WHERE nature = 'Déliberation CA';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'documents' AND table_name = 'document_nature' AND column_name = 'rapport_ca_obligatoire') THEN
        ALTER TABLE documents.document_nature ADD COLUMN rapport_ca_obligatoire boolean NOT NULL DEFAULT false;
        UPDATE documents.document_nature SET rapport_ca_obligatoire = true WHERE nature = 'Déliberation CA';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'documents' AND table_name = 'document_nature' AND column_name = 'mode_publication_raa') THEN
        ALTER TABLE documents.document_nature ADD COLUMN mode_publication_raa varchar(20) NOT NULL DEFAULT 'manuelle' CHECK (mode_publication_raa IN ('manuelle', 'deja_realisee', 'non_requise'));
        UPDATE documents.document_nature SET mode_publication_raa = 'deja_realisee' WHERE nature = 'Déliberation CA';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'documents' AND table_name = 'document_nature' AND column_name = 'autorise_dm') THEN
        ALTER TABLE documents.document_nature ADD COLUMN autorise_dm boolean NOT NULL DEFAULT false;
        UPDATE documents.document_nature SET autorise_dm = true WHERE nature = 'Arrêté directeur';
    END IF;
END;
$migration$;
"""


class Migration(migrations.Migration):
    dependencies = [("autorisations", "0037_document_nature_prefixes")]
    operations = [migrations.SeparateDatabaseAndState(
        # Le schéma PostgreSQL est administré exclusivement via sql/0038_types_actes_configurables.sql.
        database_operations=[],
        state_operations=[
            migrations.AddField(model_name="documentnature", name="est_acte", field=models.BooleanField(default=False, verbose_name="Type d’acte")),
            migrations.AddField(model_name="documentnature", name="actif", field=models.BooleanField(default=True)),
            migrations.AddField(model_name="documentnature", name="ordre_affichage", field=models.PositiveSmallIntegerField(default=0)),
            migrations.AddField(model_name="documentnature", name="circuit_signature", field=models.CharField(max_length=20, choices=[("direction", "Direction"), ("ca", "Conseil d’administration")], default="direction")),
            migrations.AddField(model_name="documentnature", name="rapport_ca_obligatoire", field=models.BooleanField(default=False)),
            migrations.AddField(model_name="documentnature", name="mode_publication_raa", field=models.CharField(max_length=20, choices=[("manuelle", "Publication à effectuer dans AGIDA"), ("deja_realisee", "Publication considérée comme déjà réalisée hors AGIDA"), ("non_requise", "Publication non requise")], default="manuelle")),
            migrations.AddField(model_name="documentnature", name="autorise_dm", field=models.BooleanField(default=False, verbose_name="Autoriser l’envoi de l’acte sur DM")),
        ],
    )]

