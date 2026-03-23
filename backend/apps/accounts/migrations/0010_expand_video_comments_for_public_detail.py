from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_user_subscriber_count_video_comment_count_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='videocomment',
            old_name='author',
            new_name='user',
        ),
        migrations.AddField(
            model_name='videocomment',
            name='is_deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='videocomment',
            name='like_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='videocomment',
            name='parent',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='replies',
                to='accounts.videocomment',
            ),
        ),
        migrations.AddField(
            model_name='videocomment',
            name='reply_count',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterModelOptions(
            name='videocomment',
            options={'ordering': ['-created_at', '-id']},
        ),
    ]
