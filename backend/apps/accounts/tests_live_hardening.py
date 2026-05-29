from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Gift, GiftTransaction, LiveChatMessage, LiveStream, MeowPointWallet

User = get_user_model()


class LiveHardeningAPITestCase(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(email='creator-live@example.com', password='pass1234', is_creator=True)
        self.viewer = User.objects.create_user(email='viewer-live@example.com', password='pass1234')

    def test_quick_start_returns_publish_session(self):
        self.client.force_authenticate(user=self.creator)
        response = self.client.post(reverse('live-stream-quick-start'), format='json')
        self.assertIn(response.status_code, {status.HTTP_200_OK, status.HTTP_201_CREATED})
        self.assertIn('publish_session', response.data)
        self.assertIn('publish_config', response.data)

    def test_start_is_idempotent_when_already_live(self):
        stream = LiveStream.objects.create(owner=self.creator, title='Live', status=LiveStream.STATUS_LIVE)
        self.client.force_authenticate(user=self.creator)
        response = self.client.post(reverse('live-stream-start', args=[stream.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['ok'])
        self.assertTrue(response.data['already_started'])

    def test_start_returns_409_for_ended(self):
        stream = LiveStream.objects.create(owner=self.creator, title='Ended', status=LiveStream.STATUS_ENDED)
        self.client.force_authenticate(user=self.creator)
        response = self.client.post(reverse('live-stream-start', args=[stream.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_status_has_stable_fields(self):
        stream = LiveStream.objects.create(owner=self.creator, title='Status', status=LiveStream.STATUS_READY)
        response = self.client.get(reverse('live-stream-status', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('can_start', response.data)
        self.assertIn('can_end', response.data)
        self.assertIn('effective_status', response.data)
        self.assertIn('publish', response.data)

    def test_ready_timeout_compacts_to_failed(self):
        stream = LiveStream.objects.create(
            owner=self.creator,
            title='timeout',
            status=LiveStream.STATUS_READY,
            publish_started_at=timezone.now() - timedelta(minutes=6),
        )
        response = self.client.get(reverse('live-stream-status', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        stream.refresh_from_db()
        self.assertEqual(stream.status, LiveStream.STATUS_FAILED)

    def test_chat_serializer_contains_type_payload(self):
        stream = LiveStream.objects.create(owner=self.creator, title='Chat stream', status=LiveStream.STATUS_LIVE)
        self.client.force_authenticate(user=self.viewer)
        post_response = self.client.post(
            reverse('live-chat-messages', args=[stream.id]),
            {'message_type': LiveChatMessage.TYPE_TEXT, 'content': 'hello'},
            format='json',
        )
        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        self.assertIn('type', post_response.data)
        self.assertIn('payload', post_response.data)

    def test_live_gift_send_creates_tx_and_gift_message(self):
        stream = LiveStream.objects.create(owner=self.creator, title='Gift stream', status=LiveStream.STATUS_LIVE)
        gift = Gift.objects.create(code='rose', name='Rose', points_price=1, is_active=True)
        MeowPointWallet.objects.create(user=self.viewer, balance=10)
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(reverse('live-gift-send', args=[stream.id]), {'gift_code': gift.code, 'quantity': 1}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data['ok'])
        self.assertTrue(GiftTransaction.objects.filter(stream=stream, sender=self.viewer).exists())
        self.assertTrue(LiveChatMessage.objects.filter(room__stream=stream, type=LiveChatMessage.EVENT_GIFT).exists())

    def test_live_gift_send_blocked_when_ended(self):
        stream = LiveStream.objects.create(owner=self.creator, title='Ended', status=LiveStream.STATUS_ENDED)
        gift = Gift.objects.create(code='rose2', name='Rose2', points_price=1, is_active=True)
        MeowPointWallet.objects.create(user=self.viewer, balance=10)
        self.client.force_authenticate(user=self.viewer)
        response = self.client.post(reverse('live-gift-send', args=[stream.id]), {'gift_code': gift.code, 'quantity': 1}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
