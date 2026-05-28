from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


def seed_payment_asset_rates(apps, schema_editor):
    PaymentAssetRate = apps.get_model('accounts', 'PaymentAssetRate')
    rate_map = getattr(settings, 'MEMBERSHIP_PAYMENT_ASSET_RATES', {}) or {}

    defaults = [
        ('thb_ltt', 'THB-LTT'),
        ('meow_points', 'MeowPoints'),
        ('meow_credit', 'MeowCredit'),
    ]
    for idx, (asset_code, display_name) in enumerate(defaults):
        raw_rate = rate_map.get(asset_code, '1')
        try:
            rate = Decimal(str(raw_rate))
        except Exception:
            rate = Decimal('1')
        if rate <= 0:
            rate = Decimal('1')
        PaymentAssetRate.objects.update_or_create(
            asset_code=asset_code,
            defaults={
                'display_name': display_name,
                'exchange_rate': rate,
                'is_active': True,
                'sort_order': idx,
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0064_membership_plan_semantics'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentAssetRate',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('asset_code', models.CharField(choices=[('thb_ltt', 'THB-LTT'), ('meow_points', 'MeowPoints'), ('meow_credit', 'MeowCredit')], max_length=32, unique=True)),
                ('display_name', models.CharField(max_length=64)),
                ('exchange_rate', models.DecimalField(decimal_places=8, default=1, max_digits=20)),
                ('is_active', models.BooleanField(default=True)),
                ('sort_order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True, null=True)),
            ],
            options={
                'ordering': ['sort_order', 'asset_code'],
            },
        ),
        migrations.RunPython(seed_payment_asset_rates, migrations.RunPython.noop),
    ]
