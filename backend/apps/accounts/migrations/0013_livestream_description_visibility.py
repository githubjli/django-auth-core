from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_livestream'),
    ]

    operations = [
        migrations.AddField(
            model_name='livestream',
            name='description',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='livestream',
            name='visibility',
            field=models.CharField(
                choices=[('public', 'Public'), ('unlisted', 'Unlisted'), ('private', 'Private')],
                default='public',
                max_length=20,
            ),
        ),
    ]
