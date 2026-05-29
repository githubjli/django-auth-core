from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import (
    Gift,
    GiftTransaction,
    LiveChatMessage,
    LiveStream,
    MeowCreditWallet,
    MeowPointWallet,
    User,
)


class FakeChannelLayer:
    def __init__(self):
        self.calls = []

    async def group_send(self, group_name, message):
        self.calls.append((group_name, message))


class LiveGiftMobileAPITestCase(APITestCase):
    def setUp(self):
        self.sender = User.objects.create_user(email='jenny@example.com', password='pass1234', first_name='Jenny')
        self.receiver = User.objects.create_user(email='creator@example.com', password='pass1234', first_name='Creator')
        self.stream = LiveStream.objects.create(
            owner=self.receiver,
            title='Mobile gifts',
            visibility=LiveStream.VISIBILITY_PUBLIC,
            status=LiveStream.STATUS_LIVE,
        )
        self.gift = Gift.objects.create(code='rose', name='Rose', points_price=10, is_active=True, sort_order=1)
        self.star = Gift.objects.create(code='star', name='Star', points_price=20, is_active=True, sort_order=2)

    def authenticate(self):
        self.client.force_authenticate(user=self.sender)

    def test_gift_list_returns_mobile_fields(self):
        response = self.client.get(reverse('gift-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rose = next(item for item in response.data if item['code'] == 'rose')
        self.assertEqual(rose['id'], self.gift.id)
        self.assertEqual(rose['emoji'], '🌹')
        self.assertEqual(rose['coin_cost'], self.gift.points_price)

    def test_live_amount_gift_with_meow_points_succeeds(self):
        MeowPointWallet.objects.create(user=self.sender, balance=100)
        MeowPointWallet.objects.create(user=self.receiver, balance=200)
        self.authenticate()

        response = self.client.post(
            reverse('live-gift-send', args=[self.stream.id]),
            {'amount': 10, 'payment_method': GiftTransaction.PAYMENT_MEOW_POINTS},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['ok'])
        self.assertEqual(response.data['event']['payload']['amount'], 10)
        self.assertEqual(response.data['event']['payload']['payment_method'], GiftTransaction.PAYMENT_MEOW_POINTS)
        self.assertEqual(response.data['sender_balance'], 90)
        self.assertEqual(response.data['receiver_balance'], 210)
        tx = GiftTransaction.objects.get(stream=self.stream, sender=self.sender)
        self.assertEqual(tx.target_type, GiftTransaction.TARGET_LIVE_STREAM)
        self.assertEqual(tx.target_id, self.stream.id)
        self.assertEqual(tx.payment_method, GiftTransaction.PAYMENT_MEOW_POINTS)

    def test_live_amount_gift_with_meow_credit_succeeds(self):
        MeowCreditWallet.objects.create(user=self.sender, balance=30)
        MeowCreditWallet.objects.create(user=self.receiver, balance=5)
        self.authenticate()

        response = self.client.post(
            reverse('live-gift-send', args=[self.stream.id]),
            {'amount': 10, 'payment_method': GiftTransaction.PAYMENT_MEOW_CREDIT},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['event']['message'], 'Jenny sent 10 meow_credit')
        self.assertEqual(response.data['sender_balance'], 20)
        self.assertEqual(response.data['receiver_balance'], 15)
        tx = GiftTransaction.objects.get(stream=self.stream, sender=self.sender)
        self.assertEqual(tx.payment_method, GiftTransaction.PAYMENT_MEOW_CREDIT)
        self.assertEqual(tx.credits_amount, 10)

    def test_live_fixed_gift_id_succeeds(self):
        MeowPointWallet.objects.create(user=self.sender, balance=100)
        self.authenticate()

        response = self.client.post(
            reverse('live-gift-send', args=[self.stream.id]),
            {'gift_id': self.gift.id, 'quantity': 2},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = response.data['event']['payload']
        self.assertEqual(payload['gift_id'], self.gift.id)
        self.assertEqual(payload['gift_code'], 'rose')
        self.assertEqual(payload['gift_name'], 'Rose')
        self.assertEqual(payload['quantity'], 2)
        self.assertEqual(payload['coin_cost'], 10)
        self.assertEqual(payload['total_cost'], 20)
        self.assertEqual(payload['payment_method'], GiftTransaction.PAYMENT_MEOW_POINTS)

    def test_live_fixed_gift_code_still_succeeds(self):
        MeowPointWallet.objects.create(user=self.sender, balance=100)
        self.authenticate()

        response = self.client.post(
            reverse('live-gift-send', args=[self.stream.id]),
            {'gift_code': self.star.code, 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['event']['payload']['gift_code'], 'star')
        self.assertTrue(GiftTransaction.objects.filter(stream=self.stream, gift=self.star).exists())

    def test_live_amount_gift_insufficient_balance_returns_payment_method(self):
        MeowCreditWallet.objects.create(user=self.sender, balance=5)
        self.authenticate()

        response = self.client.post(
            reverse('live-gift-send', args=[self.stream.id]),
            {'amount': 10, 'payment_method': GiftTransaction.PAYMENT_MEOW_CREDIT},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'insufficient_balance')
        self.assertEqual(response.data['detail'], 'Insufficient balance.')
        self.assertEqual(response.data['payment_method'], GiftTransaction.PAYMENT_MEOW_CREDIT)

    def test_live_gift_creates_gift_message(self):
        MeowPointWallet.objects.create(user=self.sender, balance=100)
        self.authenticate()

        response = self.client.post(
            reverse('live-gift-send', args=[self.stream.id]),
            {'gift_id': self.gift.id, 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        message = LiveChatMessage.objects.get(room__stream=self.stream, user=self.sender)
        self.assertEqual(message.message_type, LiveChatMessage.TYPE_GIFT)
        self.assertEqual(message.type, LiveChatMessage.EVENT_GIFT)

    def test_live_gift_broadcasts_message_created(self):
        MeowPointWallet.objects.create(user=self.sender, balance=100)
        self.authenticate()
        channel_layer = FakeChannelLayer()

        with patch('apps.accounts.gift_views.get_channel_layer', return_value=channel_layer):
            response = self.client.post(
                reverse('live-gift-send', args=[self.stream.id]),
                {'gift_id': self.gift.id, 'quantity': 1},
                format='json',
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(channel_layer.calls), 1)
        group_name, event = channel_layer.calls[0]
        self.assertEqual(group_name, f'live_chat_{self.stream.id}')
        self.assertEqual(event['type'], 'chat.message')
        self.assertEqual(event['event'], 'message_created')
        self.assertEqual(event['message']['message_type'], LiveChatMessage.TYPE_GIFT)
        self.assertEqual(event['message']['type'], LiveChatMessage.EVENT_GIFT)

    def test_user_balance_returns_points_credit_and_coin_alias(self):
        MeowPointWallet.objects.create(user=self.sender, balance=150)
        MeowCreditWallet.objects.create(user=self.sender, balance=20)
        self.authenticate()

        response = self.client.get(reverse('user-balance'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['meow_points'], {'balance': 150, 'currency': 'MP'})
        self.assertEqual(response.data['meow_credit'], {'balance': 20, 'currency': 'MC'})
        self.assertEqual(response.data['coins'], 150)
        self.assertEqual(response.data['currency'], 'MP')
