from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import (
    DramaEpisode,
    DramaSeries,
    DramaUnlock,
    Gift,
    GiftTransaction,
    LiveStream,
    MeowPointLedger,
    MeowPointWallet,
    MembershipPlan,
    PaymentOrder,
    User,
    UserMembership,
)
from apps.accounts.services import MeowPointService


class DramaUnlockAndAccessTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='drama-user@example.com', password='pass1234')
        self.member_user = User.objects.create_user(email='member-user@example.com', password='pass1234')
        self.series = DramaSeries.objects.create(
            title='Drama S',
            total_episodes=3,
            status=DramaSeries.STATUS_PUBLISHED,
            is_active=True,
        )
        self.free_episode = DramaEpisode.objects.create(
            series=self.series,
            episode_no=1,
            title='Free',
            is_free=True,
            unlock_type=DramaEpisode.UNLOCK_FREE,
            video_url='https://cdn.example.com/free.mp4',
            hls_url='https://cdn.example.com/free.m3u8',
            meow_points_price=0,
            is_active=True,
        )
        self.locked_episode = DramaEpisode.objects.create(
            series=self.series,
            episode_no=2,
            title='Locked',
            is_free=False,
            unlock_type=DramaEpisode.UNLOCK_MEOW_POINTS,
            video_url='https://cdn.example.com/locked.mp4',
            hls_url='https://cdn.example.com/locked.m3u8',
            meow_points_price=30,
            is_active=True,
        )
        self.membership_episode = DramaEpisode.objects.create(
            series=self.series,
            episode_no=3,
            title='Member',
            is_free=False,
            unlock_type=DramaEpisode.UNLOCK_MEMBERSHIP,
            video_url='https://cdn.example.com/member.mp4',
            hls_url='https://cdn.example.com/member.m3u8',
            meow_points_price=0,
            is_active=True,
        )

    def _grant_active_membership(self, user):
        plan = MembershipPlan.objects.create(
            code=MembershipPlan.CODE_MONTHLY,
            name='Monthly',
            price_lbc='1.00000000',
            duration_days=30,
            is_active=True,
            sort_order=1,
        )
        order = PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            amount='1.00',
            currency='THB-LTT',
            status=PaymentOrder.STATUS_PAID,
            order_no=f'MEM-{user.id}',
        )
        UserMembership.objects.create(
            user=user,
            source_order=order,
            plan=plan,
            status=UserMembership.STATUS_ACTIVE,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=1),
        )

    def test_locked_drama_episode_hides_playback_url(self):
        response = self.client.get(reverse('drama-episode-list', args=[self.series.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        locked = next(item for item in response.data['episodes'] if item['id'] == self.locked_episode.id)
        self.assertFalse(locked['can_watch'])
        self.assertIsNone(locked['playback_url'])

    def test_free_drama_episode_exposes_playback_url(self):
        response = self.client.get(reverse('drama-episode-list', args=[self.series.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        free_item = next(item for item in response.data['episodes'] if item['id'] == self.free_episode.id)
        self.assertTrue(free_item['can_watch'])
        self.assertEqual(free_item['playback_url'], self.free_episode.hls_url)

    def test_membership_episode_allows_active_member(self):
        self._grant_active_membership(self.member_user)
        self.client.force_authenticate(user=self.member_user)
        response = self.client.get(reverse('drama-episode-list', args=[self.series.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        member_item = next(item for item in response.data['episodes'] if item['id'] == self.membership_episode.id)
        self.assertTrue(member_item['can_watch'])
        self.assertEqual(member_item['playback_url'], self.membership_episode.hls_url)

    def test_unlock_by_meow_points_deducts_once(self):
        MeowPointService.add_points(user=self.user, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)

        self.client.force_authenticate(user=self.user)
        response = self.client.post(reverse('drama-episode-unlock', args=[self.locked_episode.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['points_charged'], 30)

        wallet = MeowPointWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 70)

    def test_repeated_unlock_does_not_double_charge(self):
        MeowPointService.add_points(user=self.user, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.user)

        first = self.client.post(reverse('drama-episode-unlock', args=[self.locked_episode.id]), format='json')
        second = self.client.post(reverse('drama-episode-unlock', args=[self.locked_episode.id]), format='json')
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data['points_charged'], 0)

        wallet = MeowPointWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 70)
        self.assertEqual(DramaUnlock.objects.filter(user=self.user, episode=self.locked_episode).count(), 1)

    def test_insufficient_balance_fails(self):
        MeowPointService.add_points(user=self.user, amount=5, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.user)

        response = self.client.post(reverse('drama-episode-unlock', args=[self.locked_episode.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'insufficient_balance')


class GiftFlowTestCase(APITestCase):
    def setUp(self):
        self.sender = User.objects.create_user(email='sender@example.com', password='pass1234')
        self.receiver = User.objects.create_user(email='receiver@example.com', password='pass1234')
        self.stream = LiveStream.objects.create(
            owner=self.receiver,
            title='Live 1',
            visibility=LiveStream.VISIBILITY_PUBLIC,
            status=LiveStream.STATUS_LIVE,
        )
        self.active_gift = Gift.objects.create(code='rose', name='Rose', points_price=10, is_active=True, sort_order=1)
        self.inactive_gift = Gift.objects.create(code='old', name='Old', points_price=20, is_active=False, sort_order=2)

    def test_gift_list_returns_active_gifts(self):
        response = self.client.get(reverse('gift-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['code'], 'rose')

    def test_send_gift_deducts_points_and_creates_gift_transaction(self):
        MeowPointService.add_points(user=self.sender, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('live-gift-send', args=[self.stream.id]),
            {'gift_code': 'rose', 'quantity': 3},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        wallet = MeowPointWallet.objects.get(user=self.sender)
        self.assertEqual(wallet.balance, 70)
        self.assertTrue(GiftTransaction.objects.filter(sender=self.sender, stream=self.stream, total_points=30).exists())

    def test_inactive_gift_cannot_be_sent(self):
        MeowPointService.add_points(user=self.sender, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)
        response = self.client.post(
            reverse('live-gift-send', args=[self.stream.id]),
            {'gift_code': 'old', 'quantity': 1},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sender_cannot_send_without_enough_balance(self):
        MeowPointService.add_points(user=self.sender, amount=5, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)
        response = self.client.post(
            reverse('live-gift-send', args=[self.stream.id]),
            {'gift_code': 'rose', 'quantity': 1},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'insufficient_balance')
