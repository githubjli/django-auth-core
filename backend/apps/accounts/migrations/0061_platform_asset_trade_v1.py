from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0060_shop_banner_product_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='meow_credit_price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='meow_points_price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='productorder',
            name='payment_asset',
            field=models.CharField(blank=True, choices=[('meow_points', 'Meow Points'), ('meow_credit', 'Meow Credit')], default='', max_length=24),
        ),
        migrations.AddField(
            model_name='productorder',
            name='payment_method',
            field=models.CharField(choices=[('platform_asset', 'Platform Asset'), ('blockchain', 'Blockchain')], default='platform_asset', max_length=24),
        ),
        migrations.AddField(model_name='productorder', name='platform_fee_amount', field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name='productorder', name='platform_fee_rate', field=models.DecimalField(blank=True, decimal_places=4, max_digits=8, null=True)),
        migrations.AddField(model_name='productorder', name='seller_receivable_amount', field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name='productorder', name='total_amount_snapshot', field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name='productorder', name='unit_price_snapshot', field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name='sellerpayout', name='asset_type', field=models.CharField(blank=True, choices=[('meow_points', 'Meow Points'), ('meow_credit', 'Meow Credit')], default='', max_length=24)),
        migrations.AddField(model_name='sellerpayout', name='gross_amount', field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name='sellerpayout', name='net_amount', field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name='sellerpayout', name='platform_fee_amount', field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
        migrations.AddField(model_name='sellerpayout', name='platform_fee_rate', field=models.DecimalField(blank=True, decimal_places=4, max_digits=8, null=True)),
        migrations.CreateModel(
            name='PlatformAssetLedger',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asset_type', models.CharField(choices=[('meow_points', 'Meow Points'), ('meow_credit', 'Meow Credit')], max_length=24)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=18)),
                ('direction', models.CharField(choices=[('credit', 'Credit'), ('debit', 'Debit')], default='credit', max_length=12)),
                ('biz_type', models.CharField(choices=[('platform_commission', 'Platform Commission'), ('refund_adjustment', 'Refund Adjustment')], max_length=32)),
                ('biz_id', models.PositiveIntegerField(blank=True, null=True)),
                ('order_no', models.CharField(blank=True, default='', max_length=64)),
                ('note', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='UserAssetBalance',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asset_type', models.CharField(choices=[('meow_points', 'Meow Points'), ('meow_credit', 'Meow Credit')], max_length=24)),
                ('balance', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True, blank=True, null=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='asset_balances', to='accounts.user')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('user', 'asset_type'), name='unique_user_asset_balance')]},
        ),
        migrations.CreateModel(
            name='UserAssetTransaction',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asset_type', models.CharField(choices=[('meow_points', 'Meow Points'), ('meow_credit', 'Meow Credit')], max_length=24)),
                ('direction', models.CharField(choices=[('debit', 'Debit'), ('credit', 'Credit')], max_length=12)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=18)),
                ('balance_before', models.DecimalField(decimal_places=2, max_digits=18)),
                ('balance_after', models.DecimalField(decimal_places=2, max_digits=18)),
                ('biz_type', models.CharField(choices=[('product_order', 'Product Order'), ('product_refund', 'Product Refund'), ('seller_payout', 'Seller Payout'), ('platform_fee', 'Platform Fee')], max_length=24)),
                ('biz_id', models.PositiveIntegerField(blank=True, null=True)),
                ('order_no', models.CharField(blank=True, default='', max_length=64)),
                ('note', models.CharField(blank=True, default='', max_length=255)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='asset_transactions', to='accounts.user')),
            ],
        ),
        migrations.AddField(
            model_name='productrefundrequest',
            name='refunded_asset_transaction',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='refund_requests', to='accounts.userassettransaction'),
        ),
    ]
