from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0041_dramaseries_owner_and_episode_creator_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='DramaSeriesView',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('session_key', models.CharField(blank=True, default='', max_length=64)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('series', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='views', to='accounts.dramaseries')),
                ('viewer', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='drama_series_views', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at', '-id']},
        ),
    ]
