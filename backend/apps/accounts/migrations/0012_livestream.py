import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import apps.accounts.models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_video_status_visibility_updated_at'),
    ]

    operations = [
        migrations.CreateModel(
            name='LiveStream',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=255)),
                ('status', models.CharField(choices=[('idle', 'Idle'), ('live', 'Live'), ('ended', 'Ended')], default='idle', max_length=20)),
                ('stream_key', models.CharField(default=apps.accounts.models.generate_stream_key, max_length=255, unique=True)),
                ('viewer_count', models.PositiveIntegerField(default=0)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('ended_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('category', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='live_streams', to='accounts.category')),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='live_streams', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at', '-id']},
        ),
    ]
