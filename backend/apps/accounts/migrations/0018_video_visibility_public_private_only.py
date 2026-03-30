from django.db import migrations, models


def normalize_video_visibility(apps, schema_editor):
    Video = apps.get_model('accounts', 'Video')
    Video.objects.filter(visibility='unlisted').update(visibility='private')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0017_user_is_creator'),
    ]

    operations = [
        migrations.RunPython(normalize_video_visibility, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='video',
            name='visibility',
            field=models.CharField(
                choices=[('public', 'Public'), ('private', 'Private')],
                default='public',
                max_length=20,
            ),
        ),
    ]
