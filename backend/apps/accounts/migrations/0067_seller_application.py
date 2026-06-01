import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0066_wallet_decimalization'),
    ]

    operations = [
        migrations.CreateModel(
            name='SellerApplication',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('store_name', models.CharField(max_length=255)),
                ('business_type', models.CharField(choices=[('individual', 'Individual'), ('company', 'Company')], max_length=20)),
                ('business_description', models.TextField()),
                ('contact_phone', models.CharField(max_length=50)),
                ('contact_email', models.EmailField(max_length=254)),
                ('business_license_url', models.URLField(blank=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=20)),
                ('rejection_reason', models.TextField(blank=True)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True, blank=True, null=True)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_seller_applications', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seller_applications', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-submitted_at', '-id'],
            },
        ),
        migrations.AddConstraint(
            model_name='sellerapplication',
            constraint=models.UniqueConstraint(condition=models.Q(status='pending'), fields=('user',), name='unique_pending_seller_application_per_user'),
        ),
    ]
