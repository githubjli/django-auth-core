from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0062_savedproduct'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentorder',
            name='amount_snapshot',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='paymentorder',
            name='asset_transaction',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='membership_payment_orders', to='accounts.userassettransaction'),
        ),
        migrations.AddField(
            model_name='paymentorder',
            name='paid_amount',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='paymentorder',
            name='payment_asset',
            field=models.CharField(choices=[('thb_ltt', 'THB-LTT'), ('meow_points', 'Meow Points'), ('meow_credit', 'Meow Credit')], default='thb_ltt', max_length=24),
        ),
        migrations.AddField(
            model_name='paymentorder',
            name='payment_method_code',
            field=models.CharField(choices=[('blockchain', 'Blockchain'), ('platform_asset', 'Platform Asset')], default='blockchain', max_length=24),
        ),
        migrations.AlterField(
            model_name='userassettransaction',
            name='biz_type',
            field=models.CharField(choices=[('product_order', 'Product Order'), ('product_refund', 'Product Refund'), ('seller_payout', 'Seller Payout'), ('platform_fee', 'Platform Fee'), ('membership_order', 'Membership Order')], max_length=24),
        ),
    ]
