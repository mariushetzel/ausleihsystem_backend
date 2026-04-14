# Generated manually on 2026-03-04
# Korrigiert: Entfernt unique=True von Warenkategorie.name
# Fügt UniqueConstraint für VerbleibOrt hinzu

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chafon_api', '0008_alter_verbleibort_name_and_more'),
    ]

    operations = [
        # Entfernt unique=True von Warenkategorie.name (war doppelt mit Constraint)
        migrations.AlterField(
            model_name='warenkategorie',
            name='name',
            field=models.CharField(max_length=100),
        ),
        # Fügt UniqueConstraint für VerbleibOrt hinzu (nur für aktive)
        migrations.AddConstraint(
            model_name='verbleibort',
            constraint=models.UniqueConstraint(
                condition=models.Q(('aktiv', True)),
                fields=('name',),
                name='unique_verbleib_name_when_active'
            ),
        ),
    ]
