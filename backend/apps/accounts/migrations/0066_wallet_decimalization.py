from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0065_payment_asset_rate'),
    ]

    operations = [
        migrations.AlterField(
            model_name='meowcreditwallet',
            name='balance',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowcreditwallet',
            name='total_adjusted',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowcreditwallet',
            name='total_recharged',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowcreditwallet',
            name='total_redeemed',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowcreditwallet',
            name='total_spent',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowcreditledger',
            name='amount',
            field=models.DecimalField(decimal_places=2, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowcreditledger',
            name='balance_after',
            field=models.DecimalField(decimal_places=2, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowcreditledger',
            name='balance_before',
            field=models.DecimalField(decimal_places=2, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowpointwallet',
            name='balance',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowpointwallet',
            name='total_bonus',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowpointwallet',
            name='total_earned',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowpointwallet',
            name='total_purchased',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowpointwallet',
            name='total_spent',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowpointledger',
            name='amount',
            field=models.DecimalField(decimal_places=2, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowpointledger',
            name='balance_after',
            field=models.DecimalField(decimal_places=2, max_digits=18),
        ),
        migrations.AlterField(
            model_name='meowpointledger',
            name='balance_before',
            field=models.DecimalField(decimal_places=2, max_digits=18),
        ),
    ]
