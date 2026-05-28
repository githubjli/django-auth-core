from django.db import migrations, models


def copy_price_to_base(apps, schema_editor):
    MembershipPlan = apps.get_model('accounts', 'MembershipPlan')
    for plan in MembershipPlan.objects.all().iterator():
        if plan.base_price_amount is None:
            plan.base_price_amount = plan.price_lbc
            plan.save(update_fields=['base_price_amount'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0063_membership_payment_assets'),
    ]

    operations = [
        migrations.AddField(
            model_name='membershipplan',
            name='allow_blockchain_payment',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='membershipplan',
            name='allow_meow_credit_payment',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='membershipplan',
            name='allow_meow_points_payment',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='membershipplan',
            name='base_price_amount',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='membershipplan',
            name='base_price_asset',
            field=models.CharField(default='thb_ltt', max_length=24),
        ),
        migrations.AddField(
            model_name='paymentorder',
            name='exchange_rate_snapshot',
            field=models.DecimalField(blank=True, decimal_places=8, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='userassettransaction',
            name='metadata',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='membershipplan',
            name='price_lbc',
            field=models.DecimalField(decimal_places=8, help_text='legacy/base price, kept for backward compatibility.', max_digits=18),
        ),
        migrations.RunPython(copy_price_to_base, migrations.RunPython.noop),
    ]
