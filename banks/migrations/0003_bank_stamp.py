from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('banks', '0002_add_seo_fields_to_bank'),
    ]

    operations = [
        migrations.AddField(
            model_name='bank',
            name='stamp',
            field=models.ImageField(blank=True, null=True, upload_to='banks/stamps/', verbose_name='Cachet officiel (PNG transparent recommandé)'),
        ),
    ]
