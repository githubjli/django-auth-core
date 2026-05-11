from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0044_manualmembershippayment'),
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
                ],
                default='pending',
                max_length=24,
            ),
        ),
    ]
