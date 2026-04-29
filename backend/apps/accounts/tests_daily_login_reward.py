from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import DailyLoginReward, MeowPointLedger, MeowPointWallet, User
from apps.accounts.services import MeowPointService


class DailyLoginRewardServiceTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='daily@example.com', password='pass1234')

    def test_next_day_can_grant_again_via_service(self):
        day1 = timezone.localdate()
        day2 = day1 + timedelta(days=1)

        result1 = MeowPointService.grant_daily_login_reward(user=self.user, reward_date=day1)
        result2 = MeowPointService.grant_daily_login_reward(user=self.user, reward_date=day2)

        self.assertTrue(result1['granted'])
        self.assertTrue(result2['granted'])
        self.assertEqual(DailyLoginReward.objects.filter(user=self.user).count(), 2)


class DailyLoginRewardLoginFlowTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='login-reward@example.com', password='pass1234')

    def test_first_successful_login_grants_reward_and_tokens(self):
        response = self.client.post(reverse('auth-login'), {'email': self.user.email, 'password': 'pass1234'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)
        self.assertIn('daily_login_reward', response.data)
        self.assertTrue(response.data['daily_login_reward']['granted'])
        self.assertEqual(response.data['daily_login_reward']['points_amount'], 10)

        wallet = MeowPointWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 10)
        self.assertTrue(MeowPointLedger.objects.filter(user=self.user, target_type='daily_login_reward').exists())
        self.assertEqual(DailyLoginReward.objects.filter(user=self.user, reward_date=timezone.localdate()).count(), 1)

    def test_second_login_same_day_does_not_grant_again(self):
        first = self.client.post(reverse('auth-login'), {'email': self.user.email, 'password': 'pass1234'}, format='json')
        second = self.client.post(reverse('auth-login'), {'email': self.user.email, 'password': 'pass1234'}, format='json')
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertFalse(second.data['daily_login_reward']['granted'])

        wallet = MeowPointWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 10)
        self.assertEqual(MeowPointLedger.objects.filter(user=self.user, target_type='daily_login_reward').count(), 1)
        self.assertEqual(DailyLoginReward.objects.filter(user=self.user, reward_date=timezone.localdate()).count(), 1)
