from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.constants import TOKEN_SYMBOL
from apps.accounts.models import (
    MeowCreditLedger,
    MeowCreditPackage,
    MeowCreditRecharge,
    MeowCreditRedeemRequest,
    MeowCreditWallet,
    PaymentOrder,
)
from apps.accounts.services import MeowCreditService

User = get_user_model()


@override_settings(LBRY_PLATFORM_RECEIVE_ADDRESS='bTestMeowCreditAddress')
class MeowCreditAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='credit@example.com', password='pass12345')
        self.client.force_authenticate(self.user)
        self.package = MeowCreditPackage.objects.create(
            code='starter',
            name='Starter',
            credit_amount=100,
            bonus_credit=10,
            price_amount=Decimal('50.00'),
            price_currency=TOKEN_SYMBOL,
            status=MeowCreditPackage.STATUS_ACTIVE,
        )

    def test_create_wallet_and_get_initial_balance(self):
        wallet = MeowCreditService.get_or_create_wallet(self.user)
        self.assertEqual(wallet.balance, 0)
        response = self.client.get(reverse('meow-credit-wallet'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['balance'], 0)

    def test_get_active_packages(self):
        MeowCreditPackage.objects.create(
            code='inactive',
            name='Inactive',
            credit_amount=1,
            price_amount=Decimal('1.00'),
            status=MeowCreditPackage.STATUS_INACTIVE,
        )
        response = self.client.get(reverse('meow-credit-packages'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.data.get('results', response.data)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]['code'], 'starter')
        self.assertEqual(payload[0]['price_currency'], TOKEN_SYMBOL)
        self.assertEqual(payload[0]['display_currency'], TOKEN_SYMBOL)

    def test_recharge_info_does_not_create_records_and_returns_thb_ltt(self):
        response = self.client.get(reverse('meow-credit-recharge-info'), {'package_code': 'starter'})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(MeowCreditRecharge.objects.count(), 0)
        self.assertEqual(PaymentOrder.objects.count(), 0)
        self.assertEqual(response.data['package_code'], 'starter')
        self.assertEqual(response.data['package_name'], 'Starter')
        self.assertEqual(response.data['credit_amount'], 100)
        self.assertEqual(response.data['bonus_credit'], 10)
        self.assertEqual(response.data['total_credit'], 110)
        self.assertEqual(response.data['price_currency'], TOKEN_SYMBOL)
        self.assertEqual(response.data['display_currency'], TOKEN_SYMBOL)
        self.assertEqual(response.data['expected_amount'], '50.00')
        self.assertIsInstance(response.data['expected_amount'], str)
        self.assertEqual(response.data['pay_to_address'], 'bTestMeowCreditAddress')
        self.assertEqual(response.data['required_confirmations'], 0)
        self.assertIn('50.00 THB-LTT', response.data['notice'])
        self.assertNotIn('expected_amount_lbc', response.data)

    def test_submit_txid_creates_recharge_and_payment_order_without_crediting_wallet(self):
        response = self.client.post(
            reverse('meow-credit-recharge-submit-txid'),
            {'package_code': 'starter', 'txid': 'tx-credit-001'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(MeowCreditRecharge.objects.count(), 1)
        self.assertEqual(PaymentOrder.objects.count(), 1)
        payment_order = PaymentOrder.objects.get()
        recharge = MeowCreditRecharge.objects.get()
        self.assertEqual(recharge.payment_order_id, payment_order.id)
        self.assertEqual(payment_order.txid, 'tx-credit-001')
        self.assertEqual(payment_order.target_type, 'meow_credit_package')
        self.assertEqual(payment_order.target_id, self.package.id)
        self.assertEqual(payment_order.amount, Decimal('0.00'))
        self.assertEqual(payment_order.expected_amount_lbc, Decimal('50.00'))
        self.assertEqual(payment_order.currency, TOKEN_SYMBOL)
        self.assertEqual(payment_order.pay_to_address, 'bTestMeowCreditAddress')
        self.assertEqual(response.data['txid'], 'tx-credit-001')
        self.assertFalse(MeowCreditWallet.objects.filter(user=self.user).exists())

    def test_submit_txid_is_idempotent_per_user_and_txid(self):
        payload = {'package_code': 'starter', 'txid': 'tx-credit-duplicate'}
        first = self.client.post(reverse('meow-credit-recharge-submit-txid'), payload, format='json')
        second = self.client.post(reverse('meow-credit-recharge-submit-txid'), payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data['order_no'], second.data['order_no'])
        self.assertEqual(MeowCreditRecharge.objects.count(), 1)
        self.assertEqual(PaymentOrder.objects.count(), 1)

    def test_submit_txid_paid_detail_auto_credits_once(self):
        created = self.client.post(
            reverse('meow-credit-recharge-submit-txid'),
            {'package_code': 'starter', 'txid': 'tx-credit-paid'},
            format='json',
        )
        order_no = created.data['order_no']
        payment_order = PaymentOrder.objects.get(order_no=order_no)
        payment_order.status = PaymentOrder.STATUS_PAID
        payment_order.paid_at = timezone.now()
        payment_order.save(update_fields=['status', 'paid_at', 'updated_at'])

        detail_url = reverse('meow-credit-recharge-detail', kwargs={'order_no': order_no})
        first = self.client.get(detail_url)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data['status'], 'credited')
        wallet = MeowCreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 110)
        self.assertEqual(wallet.total_recharged, 110)

        second = self.client.get(detail_url)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 110)
        self.assertEqual(MeowCreditLedger.objects.filter(user=self.user, entry_type=MeowCreditLedger.TYPE_RECHARGE).count(), 1)

    def test_create_recharge_order_uses_thb_ltt_and_expected_amount_api_name(self):
        response = self.client.post(reverse('meow-credit-recharge-list-create'), {'package_code': 'starter'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['price_currency'], TOKEN_SYMBOL)
        self.assertEqual(response.data['display_currency'], TOKEN_SYMBOL)
        self.assertEqual(str(response.data['expected_amount']), '50.00')
        self.assertEqual(response.data['pay_to_address'], 'bTestMeowCreditAddress')
        self.assertNotIn('expected_amount_lbc', response.data)
        payment_order = PaymentOrder.objects.get(order_no=response.data['order_no'])
        self.assertEqual(payment_order.currency, TOKEN_SYMBOL)
        self.assertEqual(payment_order.expected_amount_lbc, Decimal('50.00'))

    def test_paid_recharge_detail_auto_credits_once_and_records_ledger(self):
        created = self.client.post(reverse('meow-credit-recharge-list-create'), {'package_code': 'starter'}, format='json')
        order_no = created.data['order_no']
        payment_order = PaymentOrder.objects.get(order_no=order_no)
        payment_order.status = PaymentOrder.STATUS_PAID
        payment_order.paid_at = timezone.now()
        payment_order.save(update_fields=['status', 'paid_at', 'updated_at'])

        detail_url = reverse('meow-credit-recharge-detail', kwargs={'order_no': order_no})
        first = self.client.get(detail_url)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data['status'], 'credited')
        wallet = MeowCreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 110)
        self.assertEqual(wallet.total_recharged, 110)

        second = self.client.get(detail_url)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 110)
        self.assertEqual(MeowCreditLedger.objects.filter(user=self.user, entry_type=MeowCreditLedger.TYPE_RECHARGE).count(), 1)
        ledger = MeowCreditLedger.objects.get(user=self.user, entry_type=MeowCreditLedger.TYPE_RECHARGE)
        self.assertEqual(ledger.amount, 110)
        self.assertEqual(ledger.balance_before, 0)
        self.assertEqual(ledger.balance_after, 110)

    def test_redeem_submit_deducts_balance(self):
        MeowCreditService.credit_recharge(user=self.user, amount=100, payment_order=self._payment_order(), target=self.package)
        response = self.client.post(
            reverse('meow-credit-redeem-list-create'),
            {'amount': 40, 'redeem_method': 'bank', 'account_snapshot': {'name': 'Cat'}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        wallet = MeowCreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 60)
        self.assertEqual(response.data['status'], MeowCreditRedeemRequest.STATUS_PENDING)

    def test_redeem_rejected_refunds_balance(self):
        MeowCreditService.credit_recharge(user=self.user, amount=100, payment_order=self._payment_order(), target=self.package)
        redeem = MeowCreditService.create_redeem_request(user=self.user, amount=40, redeem_method='bank', account_snapshot={})
        MeowCreditService.reject_redeem_request(redeem, self.user, 'bad account')
        wallet = MeowCreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 100)
        self.assertEqual(MeowCreditLedger.objects.filter(user=self.user, entry_type=MeowCreditLedger.TYPE_REFUND).count(), 1)

    def test_redeem_completed_does_not_double_deduct(self):
        MeowCreditService.credit_recharge(user=self.user, amount=100, payment_order=self._payment_order(), target=self.package)
        redeem = MeowCreditService.create_redeem_request(user=self.user, amount=40, redeem_method='bank', account_snapshot={})
        MeowCreditService.approve_redeem_request(redeem, self.user)
        MeowCreditService.approve_redeem_request(redeem, self.user)
        wallet = MeowCreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 60)

    def test_redeem_insufficient_balance_fails(self):
        response = self.client.post(
            reverse('meow-credit-redeem-list-create'),
            {'amount': 1, 'redeem_method': 'bank', 'account_snapshot': {}},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(MeowCreditRedeemRequest.objects.exists())

    def _payment_order(self):
        return PaymentOrder.objects.create(
            user=self.user,
            order_type=PaymentOrder.TYPE_MEOW_CREDITS_RECHARGE,
            target_type='test',
            order_no=f'TEST{PaymentOrder.objects.count()}',
            amount=Decimal('1.00'),
            expected_amount_lbc=Decimal('1.00'),
            currency=TOKEN_SYMBOL,
            status=PaymentOrder.STATUS_PAID,
        )
