from django.db import migrations, models
from autorisations.utils.act_filename import DEFAULT_PATTERN, validate_act_filename


class Migration(migrations.Migration):
    dependencies = [('autorisations', '0049_etapes_archivage')]
    operations = [migrations.SeparateDatabaseAndState(database_operations=[], state_operations=[
        migrations.AddField(model_name='documentnature', name='nom_fichier_signe',
            field=models.CharField(max_length=200, default=DEFAULT_PATTERN,
                validators=[validate_act_filename], verbose_name='Nom du fichier signé',
                help_text='Texte libre et variables ; extension PDF imposée. Doublons : suffixes _2, _3, etc.')),
    ])]
