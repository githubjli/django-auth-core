from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import MeowPointLedger, MeowPointPackage, MeowPointWallet, User
from apps.accounts.services import MeowPointService


class MeowPointAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='wallet-user@example.com', password='pass1234')
        self.other_user = User.objects.create_user(email='other-wallet-user@example.com', password='pass1234')

    def test_wallet_is_created_or_returned_for_authenticated_user(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('meow-point-wallet'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['balance'], 0)
        self.assertTrue(MeowPointWallet.objects.filter(user=self.user).exists())

        response_again = self.client.get(reverse('meow-point-wallet'))
        self.assertEqual(response_again.status_code, status.HTTP_200_OK)
        self.assertEqual(MeowPointWallet.objects.filter(user=self.user).count(), 1)

    def test_active_packages_are_listed(self):
        active = MeowPointPackage.objects.create(
            code='starter',
            name='Starter',
            points_amount=100,
            bonus_points=10,
            price_amount='10.00',
            status=MeowPointPackage.STATUS_ACTIVE,
            sort_order=1,
        )
        MeowPointPackage.objects.create(
            code='hidden',
            name='Hidden',
            points_amount=200,
            bonus_points=20,
            price_amount='20.00',
            status=MeowPointPackage.STATUS_INACTIVE,
            sort_order=2,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('meow-point-packages'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['code'], active.code)
        self.assertEqual(response.data[0]['total_points'], 110)

    def test_inactive_packages_are_hidden_from_public_package_list(self):
        MeowPointPackage.objects.create(
            code='inactive-only',
            name='Inactive',
            points_amount=100,
            bonus_points=0,
            price_amount='10.00',
            status=MeowPointPackage.STATUS_INACTIVE,
            sort_order=1,
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('meow-point-packages'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_ledger_list_only_returns_current_user_entries(self):
        MeowPointLedger.objects.create(
            user=self.user,
            entry_type=MeowPointLedger.TYPE_BONUS,
            amount=20,
            balance_before=0,
            balance_after=20,
            note='welcome',
        )
        MeowPointLedger.objects.create(
            user=self.other_user,
            entry_type=MeowPointLedger.TYPE_BONUS,
            amount=30,
            balance_before=0,
            balance_after=30,
            note='other',
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('meow-point-ledger'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['note'], 'welcome')


class MeowPointServiceTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='service-user@example.com', password='pass1234')

    def test_service_add_points_writes_wallet_and_ledger_correctly(self):
        wallet, ledger = MeowPointService.add_points(
            user=self.user,
            amount=100,
            entry_type=MeowPointLedger.TYPE_PURCHASE,
            target_type='package',
            target_id=1,
            note='package purchase',
            purchased_amount=90,
            bonus_amount=10,
        )
        self.assertEqual(wallet.balance, 100)
        self.assertEqual(wallet.total_earned, 100)
        self.assertEqual(wallet.total_purchased, 90)
        self.assertEqual(wallet.total_bonus, 10)
        self.assertEqual(ledger.amount, 100)
        self.assertEqual(ledger.balance_before, 0)
        self.assertEqual(ledger.balance_after, 100)

    def test_service_spend_points_deducts_wallet_and_writes_ledger(self):
        MeowPointService.add_points(
            user=self.user,
            amount=120,
            entry_type=MeowPointLedger.TYPE_BONUS,
            note='seed',
        )
        wallet, ledger = MeowPointService.spend_points(
            user=self.user,
            amount=30,
            target_type='drama_episode',
            target_id=11,
            note='unlock episode',
        )
        self.assertEqual(wallet.balance, 90)
        self.assertEqual(wallet.total_spent, 30)
        self.assertEqual(ledger.amount, -30)
        self.assertEqual(ledger.balance_before, 120)
        self.assertEqual(ledger.balance_after, 90)

    def test_insufficient_balance_raises_clean_validation_error(self):
        with self.assertRaises(ValidationError) as exc:
            MeowPointService.spend_points(user=self.user, amount=1)
        self.assertIn('Insufficient Meow Points balance.', str(exc.exception))
