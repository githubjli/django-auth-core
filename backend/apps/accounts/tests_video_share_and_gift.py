import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import (
    Gift,
    GiftTransaction,
    MeowPointLedger,
    MeowPointWallet,
    User,
    Video,
    VideoShare,
)
from apps.accounts.services import MeowPointService


TEST_MEDIA_ROOT = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class PublicVideoShareAndGiftTestCase(APITestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def create_user(self, email):
        return User.objects.create_user(email=email, password='strong-pass-123')

    def create_video(self, *, owner=None, visibility=Video.VISIBILITY_PUBLIC, title='Shareable video'):
        owner = owner or self.create_user('video-owner@example.com')
        return Video.objects.create(
            owner=owner,
            title=title,
            description='A short video',
            visibility=visibility,
            file=SimpleUploadedFile('short.mp4', b'video-bytes', content_type='video/mp4'),
        )

    def setUp(self):
        self.owner = self.create_user('owner@example.com')
        self.sender = self.create_user('sender@example.com')
        self.video = self.create_video(owner=self.owner)
        self.active_gift = Gift.objects.create(code='rose', name='Rose', points_price=10, is_active=True, sort_order=1)
        self.inactive_gift = Gift.objects.create(code='old', name='Old', points_price=20, is_active=False, sort_order=2)

    def test_guest_can_post_share_and_increment_share_count(self):
        response = self.client.post(
            reverse('public-video-share', args=[self.video.id]),
            {'channel': 'copy_link'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'video_id': self.video.id, 'share_count': 1, 'channel': 'copy_link'})
        self.video.refresh_from_db()
        self.assertEqual(self.video.share_count, 1)
        share = VideoShare.objects.get(video=self.video)
        self.assertIsNone(share.user)
        self.assertEqual(share.channel, 'copy_link')

    def test_authenticated_share_records_user(self):
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-share', args=[self.video.id]),
            {'channel': 'whatsapp'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        share = VideoShare.objects.get(video=self.video)
        self.assertEqual(share.user, self.sender)
        self.assertEqual(response.data['share_count'], 1)

    def test_interaction_summary_returns_share_and_gift_fields(self):
        Video.objects.filter(pk=self.video.pk).update(share_count=2)
        GiftTransaction.objects.create(
            sender=self.sender,
            receiver=self.owner,
            video=self.video,
            gift=self.active_gift,
            gift_name_snapshot=self.active_gift.name,
            points_price_snapshot=self.active_gift.points_price,
            quantity=3,
            total_points=30,
        )

        response = self.client.get(reverse('public-video-interaction-summary', args=[self.video.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['video_id'], self.video.id)
        self.assertEqual(response.data['share_count'], 2)
        self.assertEqual(response.data['gift_count'], 3)
        self.assertEqual(response.data['gift_points_total'], 30)
        self.assertFalse(response.data['is_liked'])

    def test_authenticated_user_can_send_video_gift(self):
        MeowPointService.add_points(user=self.sender, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'gift_code': 'rose', 'quantity': 3},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        wallet = MeowPointWallet.objects.get(user=self.sender)
        self.assertEqual(wallet.balance, 70)
        tx = GiftTransaction.objects.get(sender=self.sender, video=self.video)
        self.assertIsNone(tx.stream)
        self.assertEqual(tx.receiver, self.owner)
        self.assertEqual(tx.total_points, 30)
        self.assertEqual(response.data['video_id'], self.video.id)

    def test_duplicate_video_gift_tap_is_debounced(self):
        MeowPointService.add_points(user=self.sender, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        first_response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'gift_code': 'rose', 'quantity': 1},
            format='json',
        )
        second_response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'gift_code': 'rose', 'quantity': 1},
            format='json',
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response.data['id'], second_response.data['id'])
        self.assertEqual(GiftTransaction.objects.filter(sender=self.sender, video=self.video).count(), 1)
        wallet = MeowPointWallet.objects.get(user=self.sender)
        self.assertEqual(wallet.balance, 90)

    def test_video_gift_insufficient_balance_returns_code(self):
        MeowPointService.add_points(user=self.sender, amount=5, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'gift_code': 'rose', 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'insufficient_balance')
        self.assertEqual(response.data['detail'], 'Insufficient Meow Points balance.')

    def test_inactive_gift_cannot_be_sent_to_video(self):
        MeowPointService.add_points(user=self.sender, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'gift_code': 'old', 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Gift is not active.')

    def test_private_video_cannot_receive_gift(self):
        private_video = self.create_video(owner=self.owner, visibility=Video.VISIBILITY_PRIVATE, title='Private video')
        MeowPointService.add_points(user=self.sender, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-gift-send', args=[private_video.id]),
            {'gift_code': 'rose', 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(GiftTransaction.objects.filter(video=private_video).exists())
