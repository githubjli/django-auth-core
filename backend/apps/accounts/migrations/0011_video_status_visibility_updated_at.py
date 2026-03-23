from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_expand_video_comments_for_public_detail'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='status',
            field=models.CharField(
                choices=[('active', 'Active'), ('flagged', 'Flagged'), ('archived', 'Archived')],
                default='active',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='video',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, default=None),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='video',
            name='visibility',
            field=models.CharField(
                choices=[('public', 'Public'), ('unlisted', 'Unlisted'), ('private', 'Private')],
                default='public',
                max_length=20,
            ),
        ),
    ]
