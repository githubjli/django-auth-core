from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_livestream_description_visibility'),
    ]

    operations = [
        migrations.AlterField(
            model_name='videocomment',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, blank=True, null=True),
        ),
    ]
