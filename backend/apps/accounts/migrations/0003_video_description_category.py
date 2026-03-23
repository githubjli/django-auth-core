from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0002_video'),
    ]

    operations = [
        migrations.AddField(
            model_name='video',
            name='category',
            field=models.CharField(
                blank=True,
                choices=[
                    ('education', 'Education'),
                    ('entertainment', 'Entertainment'),
                    ('gaming', 'Gaming'),
                    ('tech', 'Tech'),
                    ('other', 'Other'),
                ],
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name='video',
            name='description',
            field=models.TextField(blank=True),
        ),
    ]
