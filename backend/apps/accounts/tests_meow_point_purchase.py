from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import MeowPointLedger, MeowPointPackage, MeowPointPurchase, MeowPointWallet, PaymentOrder, User
from apps.accounts.services import MeowPointPurchaseService


class MeowPointPurchaseAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='purchase-user@example.com', password='pass1234')
        self.other_user = User.objects.create_user(email='purchase-other@example.com', password='pass1234')
        self.package = MeowPointPackage.objects.create(
            code='starter_100',
            name='Starter 100',
            points_amount=100,
            bonus_points=20,
            price_amount='10.00',
            status=MeowPointPackage.STATUS_ACTIVE,
            sort_order=1,
        )

    def test_create_order_from_active_package(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('meow-point-order-list-create'),
            {'package_code': self.package.code},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order = MeowPointPurchase.objects.get(order_no=response.data['order_no'])
        self.assertEqual(order.user_id, self.user.id)

    def test_cannot_create_order_from_inactive_package(self):
        self.package.status = MeowPointPackage.STATUS_INACTIVE
        self.package.save(update_fields=['status'])

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('meow-point-order-list-create'),
            {'package_code': self.package.code},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_order_snapshots_package_fields(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('meow-point-order-list-create'),
            {'package_code': self.package.code},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order = MeowPointPurchase.objects.get(order_no=response.data['order_no'])

        self.package.name = 'Changed Name'
        self.package.points_amount = 999
        self.package.save(update_fields=['name', 'points_amount'])

        self.assertEqual(order.package_code_snapshot, 'starter_100')
        self.assertEqual(order.package_name_snapshot, 'Starter 100')
        self.assertEqual(order.points_amount, 100)
        self.assertEqual(order.bonus_points, 20)
        self.assertEqual(order.total_points, 120)

    def test_tx_hint_stores_txid_without_crediting_unpaid_order(self):
        purchase = MeowPointPurchaseService().create_order(user=self.user, package_code=self.package.code)

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('meow-point-order-tx-hint', args=[purchase.order_no]),
            {'txid': 'hint-txid-001'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        purchase.refresh_from_db()
        purchase.payment_order.refresh_from_db()
        self.assertEqual(purchase.payment_order.txid, 'hint-txid-001')
        self.assertIsNone(purchase.credited_at)
        self.assertFalse(MeowPointWallet.objects.filter(user=self.user).exists())

    def test_order_list_is_user_scoped(self):
        MeowPointPurchaseService().create_order(user=self.user, package_code=self.package.code)
        MeowPointPurchaseService().create_order(user=self.other_user, package_code=self.package.code)

        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('meow-point-order-list-create'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)


class MeowPointPurchaseServiceTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='purchase-service-user@example.com', password='pass1234')
        self.package = MeowPointPackage.objects.create(
            code='pro_500',
            name='Pro 500',
            points_amount=500,
            bonus_points=50,
            price_amount='50.00',
            status=MeowPointPackage.STATUS_ACTIVE,
            sort_order=1,
        )

    def test_paid_purchase_credits_wallet(self):
        purchase = MeowPointPurchaseService().create_order(user=self.user, package_code=self.package.code)
        payment_order = purchase.payment_order
        payment_order.status = PaymentOrder.STATUS_PAID
        payment_order.paid_at = timezone.now()
        payment_order.save(update_fields=['status', 'paid_at', 'updated_at'])

        MeowPointPurchaseService().credit_paid_purchase(purchase)

        wallet = MeowPointWallet.objects.get(user=self.user)
        purchase.refresh_from_db()
        self.assertEqual(wallet.balance, 550)
        self.assertEqual(wallet.total_purchased, 500)
        self.assertEqual(wallet.total_bonus, 50)
        self.assertIsNotNone(purchase.credited_at)

    def test_repeated_credit_call_does_not_double_credit(self):
        purchase = MeowPointPurchaseService().create_order(user=self.user, package_code=self.package.code)
        purchase.payment_order.status = PaymentOrder.STATUS_PAID
        purchase.payment_order.paid_at = timezone.now()
        purchase.payment_order.save(update_fields=['status', 'paid_at', 'updated_at'])

        service = MeowPointPurchaseService()
        service.credit_paid_purchase(purchase)
        service.credit_paid_purchase(purchase)

        wallet = MeowPointWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 550)

    def test_ledger_records_purchase_and_bonus_separately(self):
        purchase = MeowPointPurchaseService().create_order(user=self.user, package_code=self.package.code)
        purchase.payment_order.status = PaymentOrder.STATUS_PAID
        purchase.payment_order.paid_at = timezone.now()
        purchase.payment_order.save(update_fields=['status', 'paid_at', 'updated_at'])

        MeowPointPurchaseService().credit_paid_purchase(purchase)

        entries = list(MeowPointLedger.objects.filter(user=self.user).order_by('id'))
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].entry_type, MeowPointLedger.TYPE_PURCHASE)
        self.assertEqual(entries[0].amount, 500)
        self.assertEqual(entries[1].entry_type, MeowPointLedger.TYPE_BONUS)
        self.assertEqual(entries[1].amount, 50)
