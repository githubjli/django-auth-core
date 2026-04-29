from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0042_dramaseriesview'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyLoginReward',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reward_date', models.DateField()),
                ('points_amount', models.PositiveIntegerField(default=10)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('ledger_entry', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='daily_login_reward', to='accounts.meowpointledger')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_login_rewards', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-reward_date', '-id']},
        ),
        migrations.AddConstraint(
            model_name='dailyloginreward',
            constraint=models.UniqueConstraint(fields=('user', 'reward_date'), name='unique_daily_login_reward_per_user_date'),
        ),
    ]
