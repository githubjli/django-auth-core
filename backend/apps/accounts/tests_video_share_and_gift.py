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
    MeowCreditLedger,
    MeowCreditWallet,
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
        self.assertEqual(response.data['gift_amount_total'], 30)
        self.assertFalse(response.data['is_liked'])



    def test_video_points_gift_success_transfers_points_to_receiver(self):
        sender_points = MeowPointWallet.objects.create(user=self.sender, balance=100)
        receiver_points = MeowPointWallet.objects.create(user=self.owner, balance=50)
        sender_credits = MeowCreditWallet.objects.create(user=self.sender, balance=77)
        receiver_credits = MeowCreditWallet.objects.create(user=self.owner, balance=88)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'amount': 30, 'payment_method': 'meow_points'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['video_id'], self.video.id)
        self.assertEqual(response.data['receiver_id'], self.owner.id)
        self.assertEqual(response.data['amount'], 30)
        self.assertEqual(response.data['payment_method'], 'meow_points')
        self.assertEqual(response.data['points_charged'], 30)
        self.assertEqual(response.data['credits_charged'], 0)
        self.assertEqual(response.data['sender_balance'], 70)
        self.assertEqual(response.data['receiver_balance'], 80)

        sender_points.refresh_from_db()
        receiver_points.refresh_from_db()
        sender_credits.refresh_from_db()
        receiver_credits.refresh_from_db()
        self.assertEqual(sender_points.balance, 70)
        self.assertEqual(receiver_points.balance, 80)
        self.assertEqual(sender_credits.balance, 77)
        self.assertEqual(receiver_credits.balance, 88)

        tx = GiftTransaction.objects.get(pk=response.data['gift_transaction_id'])
        self.assertEqual(tx.sender, self.sender)
        self.assertEqual(tx.receiver, self.owner)
        self.assertEqual(tx.video, self.video)
        self.assertIsNone(tx.drama_series)
        self.assertIsNone(tx.stream)
        self.assertEqual(tx.target_type, GiftTransaction.TARGET_VIDEO)
        self.assertEqual(tx.target_id, self.video.id)
        self.assertEqual(tx.payment_method, GiftTransaction.PAYMENT_MEOW_POINTS)
        self.assertEqual(tx.amount, 30)
        self.assertEqual(tx.points_amount, 30)
        self.assertEqual(tx.credits_amount, 0)
        self.assertIsNotNone(tx.sender_point_ledger)
        self.assertIsNotNone(tx.receiver_point_ledger)
        self.assertIsNone(tx.sender_credit_ledger)
        self.assertIsNone(tx.receiver_credit_ledger)
        self.assertEqual(tx.sender_point_ledger.sent_gift_transaction, tx)
        self.assertEqual(tx.receiver_point_ledger.received_gift_transaction, tx)
        self.video.refresh_from_db()
        self.assertEqual(self.video.gift_count, 1)
        self.assertEqual(self.video.gift_amount_total, 30)

    def test_video_credit_gift_success_transfers_credits_to_receiver(self):
        sender_points = MeowPointWallet.objects.create(user=self.sender, balance=44)
        receiver_points = MeowPointWallet.objects.create(user=self.owner, balance=55)
        sender_credits = MeowCreditWallet.objects.create(user=self.sender, balance=100)
        receiver_credits = MeowCreditWallet.objects.create(user=self.owner, balance=50)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'amount': 30, 'payment_method': 'meow_credit'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['payment_method'], 'meow_credit')
        self.assertEqual(response.data['points_charged'], 0)
        self.assertEqual(response.data['credits_charged'], 30)
        self.assertEqual(response.data['sender_balance'], 70)
        self.assertEqual(response.data['receiver_balance'], 80)

        sender_points.refresh_from_db()
        receiver_points.refresh_from_db()
        sender_credits.refresh_from_db()
        receiver_credits.refresh_from_db()
        self.assertEqual(sender_points.balance, 44)
        self.assertEqual(receiver_points.balance, 55)
        self.assertEqual(sender_credits.balance, 70)
        self.assertEqual(receiver_credits.balance, 80)

        tx = GiftTransaction.objects.get(pk=response.data['gift_transaction_id'])
        self.assertEqual(tx.target_type, GiftTransaction.TARGET_VIDEO)
        self.assertEqual(tx.target_id, self.video.id)
        self.assertEqual(tx.payment_method, GiftTransaction.PAYMENT_MEOW_CREDIT)
        self.assertEqual(tx.amount, 30)
        self.assertEqual(tx.points_amount, 0)
        self.assertEqual(tx.credits_amount, 30)
        self.assertIsNone(tx.sender_point_ledger)
        self.assertIsNone(tx.receiver_point_ledger)
        self.assertIsNotNone(tx.sender_credit_ledger)
        self.assertIsNotNone(tx.receiver_credit_ledger)

    def test_video_gift_invalid_amount_rejected(self):
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'amount': 2, 'payment_method': 'meow_points'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('amount', response.data)

    def test_video_gift_insufficient_points_rolls_back(self):
        MeowPointWallet.objects.create(user=self.sender, balance=10)
        MeowPointWallet.objects.create(user=self.owner, balance=5)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'amount': 30, 'payment_method': 'meow_points'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                'code': 'insufficient_balance',
                'detail': 'Insufficient balance.',
                'payment_method': 'meow_points',
            },
        )
        self.assertFalse(GiftTransaction.objects.filter(video=self.video).exists())
        self.assertFalse(MeowPointLedger.objects.filter(entry_type__in=[MeowPointLedger.TYPE_GIFT_SPEND, MeowPointLedger.TYPE_GIFT_RECEIVED]).exists())
        self.video.refresh_from_db()
        self.assertEqual(self.video.gift_count, 0)
        self.assertEqual(self.video.gift_amount_total, 0)

    def test_video_gift_insufficient_credit_rolls_back(self):
        MeowCreditWallet.objects.create(user=self.sender, balance=10)
        MeowCreditWallet.objects.create(user=self.owner, balance=5)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('public-video-gift-send', args=[self.video.id]),
            {'amount': 30, 'payment_method': 'meow_credit'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data,
            {
                'code': 'insufficient_balance',
                'detail': 'Insufficient balance.',
                'payment_method': 'meow_credit',
            },
        )
        self.assertFalse(GiftTransaction.objects.filter(video=self.video).exists())
        self.assertFalse(MeowCreditLedger.objects.filter(entry_type__in=[MeowCreditLedger.TYPE_GIFT_SPEND, MeowCreditLedger.TYPE_GIFT_RECEIVED]).exists())
        self.video.refresh_from_db()
        self.assertEqual(self.video.gift_count, 0)
        self.assertEqual(self.video.gift_amount_total, 0)

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
        self.assertEqual(response.data['detail'], 'Insufficient balance.')
        self.assertEqual(response.data['payment_method'], 'meow_points')

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
