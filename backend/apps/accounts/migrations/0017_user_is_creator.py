from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0016_livestream_payment_address'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_creator',
            field=models.BooleanField(default=False),
        ),
    ]
