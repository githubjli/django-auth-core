from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0040_video_access_type_video_preview_seconds'),
    ]

    operations = [
        migrations.AddField(
            model_name='dramaseries',
            name='owner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='drama_series', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='dramaepisode',
            name='description',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='dramaepisode',
            name='thumbnail',
            field=models.FileField(blank=True, upload_to='dramas/thumbnails/'),
        ),
        migrations.AddField(
            model_name='dramaepisode',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('published', 'Published'), ('archived', 'Archived')], default='published', max_length=20),
        ),
    ]
