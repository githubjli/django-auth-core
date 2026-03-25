from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0014_alter_videocomment_updated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='avatar',
            field=models.FileField(blank=True, upload_to='avatars/'),
        ),
        migrations.AddField(
            model_name='user',
            name='bio',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='user',
            name='language',
            field=models.CharField(default='en-US', max_length=10),
        ),
        migrations.AddField(
            model_name='user',
            name='theme',
            field=models.CharField(default='system', max_length=10),
        ),
        migrations.AddField(
            model_name='user',
            name='timezone',
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
