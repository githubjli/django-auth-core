from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0025_billingplan_billingsubscription'),
    ]

    operations = [
        migrations.AddField(
            model_name='billingplan',
            name='wallet_address',
            field=models.TextField(blank=True, default=''),
        ),
    ]
