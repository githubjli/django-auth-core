from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0015_user_profile_preferences'),
    ]

    operations = [
        migrations.AddField(
            model_name='livestream',
            name='payment_address',
            field=models.TextField(blank=True),
        ),
    ]
