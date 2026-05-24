from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0058_live_session_and_chat_payload'),
    ]

    operations = [
        migrations.AddField(
            model_name='livestream',
            name='thumbnail',
            field=models.ImageField(blank=True, upload_to='live/thumbnails/'),
        ),
        migrations.AddField(
            model_name='livestream',
            name='thumbnail_capture_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='livestream',
            name='thumbnail_capture_status',
            field=models.CharField(choices=[('pending', 'Pending'), ('success', 'Success'), ('failed', 'Failed')], default='pending', max_length=16),
        ),
        migrations.AddField(
            model_name='livestream',
            name='thumbnail_captured_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
