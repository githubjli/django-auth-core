from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0043_dailyloginreward'),
    ]

    operations = [
        migrations.CreateModel(
            name='ManualMembershipPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('txid', models.CharField(max_length=128, unique=True)),
                ('expected_amount_lbc', models.DecimalField(decimal_places=8, max_digits=18)),
                ('actual_amount_lbc', models.DecimalField(blank=True, decimal_places=8, max_digits=18, null=True)),
                ('pay_to_address', models.CharField(max_length=128)),
                ('confirmations', models.PositiveIntegerField(default=0)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('verified', 'Verified'), ('rejected', 'Rejected')], default='pending', max_length=24)),
                ('reject_reason', models.TextField(blank=True, default='')),
                ('raw_tx', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True, blank=True, null=True)),
                ('verified_at', models.DateTimeField(blank=True, null=True)),
                ('membership', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manual_payment', to='accounts.usermembership')),
                ('payment_order', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='manual_membership_payment', to='accounts.paymentorder')),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='manual_membership_payments', to='accounts.membershipplan')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='manual_membership_payments', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'indexes': [
                    models.Index(fields=['user', 'status', 'created_at'], name='manual_member_user_status_idx'),
                    models.Index(fields=['status', 'created_at'], name='manual_member_status_idx'),
                ],
            },
        ),
    ]
