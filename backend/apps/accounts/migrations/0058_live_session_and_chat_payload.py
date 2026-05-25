from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0057_video_gift_totals'),
    ]

    operations = [
        migrations.AddField(
            model_name='livestream',
            name='failure_reason',
            field=models.CharField(blank=True, default='', max_length=128),
        ),
        migrations.AddField(
            model_name='livestream',
            name='last_publish_signal_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='livestream',
            name='publish_session_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='livestream',
            name='publish_session_id',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='livestream',
            name='publish_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='livechatmessage',
            name='payload',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='livechatmessage',
            name='type',
            field=models.CharField(choices=[('chat', 'Chat'), ('system', 'System'), ('gift', 'Gift'), ('product', 'Product'), ('payment', 'Payment')], default='chat', max_length=20),
        ),
        migrations.AlterField(
            model_name='livechatmessage',
            name='message_type',
            field=models.CharField(choices=[('chat', 'Chat'), ('text', 'Text'), ('system', 'System'), ('gift', 'Gift'), ('product', 'Product'), ('payment', 'Payment')], default='text', max_length=20),
        ),
        migrations.AlterField(
            model_name='livestream',
            name='status',
            field=models.CharField(choices=[('idle', 'Idle'), ('ready', 'Ready'), ('live', 'Live'), ('ended', 'Ended'), ('failed', 'Failed')], default='idle', max_length=20),
        ),
    ]
