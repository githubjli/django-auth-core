from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0045_alter_manualmembershippayment_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='manualmembershippayment',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('submitted', 'Submitted'),
                    ('dry_run_verified', 'Dry Run Verified'),
                    ('pending_confirmation', 'Pending Confirmation'),
                    ('verified', 'Verified'),
                    ('rejected', 'Rejected'),
                    ('failed', 'Failed'),
                ],
                default='pending',
                max_length=24,
            ),
        ),
    ]
