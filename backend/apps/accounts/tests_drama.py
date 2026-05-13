from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import (
    ChannelSubscription,
    DramaComment,
    DramaEpisode,
    DramaFavorite,
    DramaSeries,
    DramaShare,
    DramaUnlock,
    DramaWatchProgress,
    Gift,
    GiftTransaction,
    MeowCreditLedger,
    MeowCreditWallet,
    MeowPointLedger,
    MeowPointWallet,
    User,
)
from apps.accounts.services import MeowPointService


class DramaReadOnlyAPITestCase(APITestCase):
    def setUp(self):
        self.active_series = DramaSeries.objects.create(
            title='Bangkok Hearts',
            description='A fast-paced city romance.',
            cover=SimpleUploadedFile('cover.jpg', b'cover-bytes', content_type='image/jpeg'),
            tags=['romance', 'urban'],
            total_episodes=2,
            status=DramaSeries.STATUS_PUBLISHED,
            is_active=True,
            view_count=123,
            favorite_count=10,
        )
        self.inactive_series = DramaSeries.objects.create(
            title='Hidden Drama',
            description='Should not be listed.',
            total_episodes=1,
            status=DramaSeries.STATUS_PUBLISHED,
            is_active=False,
        )

        self.free_episode = DramaEpisode.objects.create(
            series=self.active_series,
            episode_no=1,
            title='Episode 1',
            duration_seconds=95,
            is_free=True,
            unlock_type=DramaEpisode.UNLOCK_FREE,
            meow_points_price=0,
            sort_order=1,
            video_url='https://cdn.example.com/dramas/active/e01.mp4',
            hls_url='https://cdn.example.com/dramas/active/e01.m3u8',
            is_active=True,
        )
        self.locked_episode = DramaEpisode.objects.create(
            series=self.active_series,
            episode_no=2,
            title='Episode 2',
            duration_seconds=99,
            is_free=False,
            unlock_type=DramaEpisode.UNLOCK_MEOW_POINTS,
            meow_points_price=30,
            sort_order=2,
            video_url='https://cdn.example.com/dramas/active/e02.mp4',
            hls_url='https://cdn.example.com/dramas/active/e02.m3u8',
            is_active=True,
        )
        DramaEpisode.objects.create(
            series=self.inactive_series,
            episode_no=1,
            title='Hidden Episode',
            duration_seconds=90,
            is_free=True,
            unlock_type=DramaEpisode.UNLOCK_FREE,
            sort_order=1,
            is_active=True,
        )

    def test_get_dramas_list_returns_active_series_only(self):
        response = self.client.get(reverse('drama-series-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(len(response.data['results']), 1)

        item = response.data['results'][0]
        self.assertEqual(item['id'], self.active_series.id)
        self.assertEqual(item['title'], self.active_series.title)
        self.assertEqual(item['total_episodes'], 2)
        self.assertEqual(item['free_episode_count'], 1)
        self.assertEqual(item['locked_episode_count'], 1)
        self.assertFalse(item['is_favorited'])
        self.assertIsNone(item['continue_episode_no'])
        self.assertIsNone(item['continue_progress_seconds'])

    def test_get_drama_detail_returns_expected_shape(self):
        response = self.client.get(reverse('drama-series-detail', args=[self.active_series.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.active_series.id)
        self.assertEqual(response.data['title'], self.active_series.title)
        self.assertEqual(response.data['free_episode_count'], 1)
        self.assertEqual(response.data['locked_episode_count'], 1)
        self.assertFalse(response.data['is_favorited'])
        self.assertIsNone(response.data['continue_episode_no'])
        self.assertIsNone(response.data['continue_progress_seconds'])

    def test_get_drama_episodes_returns_free_and_locked_flags(self):
        response = self.client.get(reverse('drama-episode-list', args=[self.active_series.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['series_id'], self.active_series.id)
        self.assertEqual(len(response.data['episodes']), 2)

        first = response.data['episodes'][0]
        self.assertEqual(first['id'], self.free_episode.id)
        self.assertEqual(first['episode_no'], 1)
        self.assertFalse(first['is_locked'])
        self.assertTrue(first['is_unlocked'])
        self.assertEqual(first['video_url'], self.free_episode.video_url)
        self.assertEqual(first['hls_url'], self.free_episode.hls_url)

        second = response.data['episodes'][1]
        self.assertEqual(second['id'], self.locked_episode.id)
        self.assertTrue(second['is_locked'])
        self.assertFalse(second['is_unlocked'])
        self.assertIsNone(second['video_url'])
        self.assertIsNone(second['hls_url'])

    def test_get_drama_episode_detail_by_episode_no(self):
        response = self.client.get(
            reverse('drama-episode-detail', args=[self.active_series.id, self.locked_episode.episode_no])
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.locked_episode.id)
        self.assertEqual(response.data['series_id'], self.active_series.id)
        self.assertEqual(response.data['episode_no'], 2)
        self.assertTrue(response.data['is_locked'])
        self.assertFalse(response.data['is_unlocked'])
        self.assertIsNone(response.data['video_url'])
        self.assertIsNone(response.data['hls_url'])

    def test_https_forwarded_proto_generates_https_media_urls(self):
        self.free_episode.video_url = ''
        self.free_episode.hls_url = ''
        self.free_episode.video_file = SimpleUploadedFile('e01.mp4', b'video-bytes', content_type='video/mp4')
        self.free_episode.save(update_fields=['video_url', 'hls_url', 'video_file'])

        list_response = self.client.get(
            reverse('drama-series-list'),
            HTTP_HOST='stream.meownews.online',
            HTTP_X_FORWARDED_PROTO='https',
        )
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertTrue(list_response.data['results'][0]['cover_url'].startswith('https://stream.meownews.online/media/'))

        episodes_response = self.client.get(
            reverse('drama-episode-list', args=[self.active_series.id]),
            HTTP_HOST='stream.meownews.online',
            HTTP_X_FORWARDED_PROTO='https',
        )
        self.assertEqual(episodes_response.status_code, status.HTTP_200_OK)
        first_episode = episodes_response.data['episodes'][0]
        self.assertTrue(first_episode['video_url'].startswith('https://stream.meownews.online/media/'))
        self.assertTrue(first_episode['playback_url'].startswith('https://stream.meownews.online/media/'))


class DramaPhase2APITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='viewer@example.com', password='pass1234')
        self.other_user = User.objects.create_user(email='other@example.com', password='pass1234')
        self.series = DramaSeries.objects.create(
            title='Bangkok Hearts',
            description='A fast-paced city romance.',
            total_episodes=2,
            status=DramaSeries.STATUS_PUBLISHED,
            is_active=True,
            favorite_count=0,
        )
        self.episode_1 = DramaEpisode.objects.create(
            series=self.series,
            episode_no=1,
            title='Episode 1',
            duration_seconds=95,
            is_free=True,
            unlock_type=DramaEpisode.UNLOCK_FREE,
            meow_points_price=0,
            sort_order=1,
            is_active=True,
        )
        self.episode_2 = DramaEpisode.objects.create(
            series=self.series,
            episode_no=2,
            title='Episode 2',
            duration_seconds=99,
            is_free=False,
            unlock_type=DramaEpisode.UNLOCK_MEOW_POINTS,
            meow_points_price=30,
            sort_order=2,
            is_active=True,
        )

    def test_save_progress(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('drama-progress-upsert', args=[self.series.id]),
            {'episode_id': self.episode_1.id, 'progress_seconds': 85, 'completed': False},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['series_id'], self.series.id)
        self.assertEqual(response.data['episode_id'], self.episode_1.id)
        self.assertEqual(response.data['episode_no'], self.episode_1.episode_no)
        self.assertEqual(response.data['progress_seconds'], 85)
        self.assertFalse(response.data['completed'])

    def test_update_progress_idempotently(self):
        DramaWatchProgress.objects.create(
            user=self.user,
            series=self.series,
            episode=self.episode_1,
            progress_seconds=20,
            completed=False,
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            reverse('drama-progress-upsert', args=[self.series.id]),
            {'episode_id': self.episode_2.id, 'progress_seconds': 50, 'completed': True},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(DramaWatchProgress.objects.filter(user=self.user, series=self.series).count(), 1)
        progress = DramaWatchProgress.objects.get(user=self.user, series=self.series)
        self.assertEqual(progress.episode_id, self.episode_2.id)
        self.assertEqual(progress.progress_seconds, 50)
        self.assertTrue(progress.completed)

    def test_favorite(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post(reverse('drama-favorite', args=[self.series.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_favorited'])
        self.assertEqual(response.data['favorite_count'], 1)
        self.series.refresh_from_db()
        self.assertEqual(self.series.favorite_count, 1)

    def test_unfavorite(self):
        DramaFavorite.objects.create(user=self.user, series=self.series)
        self.series.favorite_count = 1
        self.series.save(update_fields=['favorite_count'])
        self.client.force_authenticate(user=self.user)
        response = self.client.delete(reverse('drama-favorite', args=[self.series.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['is_favorited'])
        self.assertEqual(response.data['favorite_count'], 0)
        self.assertFalse(DramaFavorite.objects.filter(user=self.user, series=self.series).exists())

    def test_favorites_are_user_scoped(self):
        DramaFavorite.objects.create(user=self.user, series=self.series)
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(reverse('account-drama-favorites'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

    def test_progress_is_user_scoped(self):
        DramaWatchProgress.objects.create(
            user=self.user,
            series=self.series,
            episode=self.episode_1,
            progress_seconds=85,
            completed=False,
        )
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(reverse('account-drama-progress'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

    def test_authenticated_drama_list_includes_favorite_and_progress_state(self):
        DramaFavorite.objects.create(user=self.user, series=self.series)
        DramaWatchProgress.objects.create(
            user=self.user,
            series=self.series,
            episode=self.episode_2,
            progress_seconds=42,
            completed=False,
        )
        self.client.force_authenticate(user=self.user)
        response = self.client.get(reverse('drama-series-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data['results'][0]
        self.assertTrue(item['is_favorited'])
        self.assertEqual(item['continue_episode_no'], 2)
        self.assertEqual(item['continue_progress_seconds'], 42)

    def test_anonymous_drama_list_still_works(self):
        DramaFavorite.objects.create(user=self.user, series=self.series)
        DramaWatchProgress.objects.create(
            user=self.user,
            series=self.series,
            episode=self.episode_2,
            progress_seconds=42,
            completed=False,
        )
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('drama-series-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data['results'][0]
        self.assertFalse(item['is_favorited'])
        self.assertIsNone(item['continue_episode_no'])
        self.assertIsNone(item['continue_progress_seconds'])


class DramaInteractionAPITestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='owner@example.com', password='pass1234')
        self.user = User.objects.create_user(email='commenter@example.com', password='pass1234')
        self.series = DramaSeries.objects.create(
            owner=self.owner,
            title='Interactive Shorts',
            status=DramaSeries.STATUS_PUBLISHED,
            is_active=True,
        )

    def test_comment_list_and_create(self):
        self.client.force_authenticate(user=self.user)
        create_response = self.client.post(
            reverse('drama-comments', args=[self.series.id]),
            {'content': 'So good!'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data['content'], 'So good!')
        self.series.refresh_from_db()
        self.assertEqual(self.series.comment_count, 1)

        list_response = self.client.get(reverse('drama-comments', args=[self.series.id]))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data['count'], 1)
        self.assertEqual(list_response.data['results'][0]['content'], 'So good!')

    def test_share_increments_count(self):
        response = self.client.post(
            reverse('drama-share', args=[self.series.id]),
            {'channel': 'copy_link'},
            format='json',
            REMOTE_ADDR='1.2.3.4',
            HTTP_USER_AGENT='drama-test',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['share_count'], 1)
        self.series.refresh_from_db()
        self.assertEqual(self.series.share_count, 1)
        share = DramaShare.objects.get(series=self.series)
        self.assertEqual(share.channel, 'copy_link')
        self.assertEqual(share.ip_address, '1.2.3.4')

    def test_interaction_summary_anonymous(self):
        DramaComment.objects.create(series=self.series, user=self.user, content='Hello')
        DramaSeries.objects.filter(pk=self.series.pk).update(comment_count=1, share_count=2, favorite_count=3, view_count=4)
        response = self.client.get(reverse('drama-interaction-summary', args=[self.series.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['series_id'], self.series.id)
        self.assertEqual(response.data['favorite_count'], 3)
        self.assertEqual(response.data['comment_count'], 1)
        self.assertEqual(response.data['share_count'], 2)
        self.assertEqual(response.data['view_count'], 4)
        self.assertFalse(response.data['viewer_is_favorited'])
        self.assertFalse(response.data['viewer_is_subscribed'])
        self.assertEqual(response.data['owner_id'], self.owner.id)
        self.assertEqual(response.data['subscriber_count'], self.owner.subscriber_count)

    def test_interaction_summary_authenticated_favorite_and_subscribed(self):
        DramaFavorite.objects.create(user=self.user, series=self.series)
        ChannelSubscription.objects.create(channel=self.owner, subscriber=self.user)
        self.owner.subscriber_count = 1
        self.owner.save(update_fields=['subscriber_count'])
        self.client.force_authenticate(user=self.user)

        response = self.client.get(reverse('drama-interaction-summary', args=[self.series.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['viewer_is_favorited'])
        self.assertTrue(response.data['viewer_is_subscribed'])
        self.assertEqual(response.data['subscriber_count'], 1)



class DramaOwnerInfoAPITestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='owner-info@example.com', password='pass1234', first_name='Drama', last_name='Owner')
        self.owner.subscriber_count = 3
        self.owner.save(update_fields=['subscriber_count'])
        self.viewer = User.objects.create_user(email='viewer-info@example.com', password='pass1234')
        self.series = DramaSeries.objects.create(
            owner=self.owner,
            title='Owner Shorts',
            status=DramaSeries.STATUS_PUBLISHED,
            is_active=True,
        )

    def test_drama_list_includes_owner_info(self):
        response = self.client.get(reverse('drama-series-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data['results'][0]
        self.assertEqual(item['owner_id'], self.owner.id)
        self.assertEqual(item['owner_name'], self.owner.display_name)
        self.assertIsNone(item['owner_avatar_url'])
        self.assertFalse(item['viewer_is_subscribed'])
        self.assertEqual(item['subscriber_count'], 3)

    def test_viewer_is_subscribed_true_for_followed_owner(self):
        ChannelSubscription.objects.create(channel=self.owner, subscriber=self.viewer)
        self.client.force_authenticate(user=self.viewer)

        response = self.client.get(reverse('drama-series-detail', args=[self.series.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['viewer_is_subscribed'])

    def test_owner_null_does_not_crash(self):
        self.series.owner = None
        self.series.save(update_fields=['owner'])

        response = self.client.get(reverse('drama-series-detail', args=[self.series.id]))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['owner_id'])
        self.assertIsNone(response.data['owner_name'])
        self.assertIsNone(response.data['owner_avatar_url'])
        self.assertFalse(response.data['viewer_is_subscribed'])
        self.assertEqual(response.data['subscriber_count'], 0)



class DramaUnlockPaymentMethodAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='unlocker@example.com', password='pass1234')
        self.series = DramaSeries.objects.create(
            title='Unlockable Shorts',
            status=DramaSeries.STATUS_PUBLISHED,
            is_active=True,
        )
        self.episode = DramaEpisode.objects.create(
            series=self.series,
            episode_no=1,
            title='Premium Episode',
            duration_seconds=90,
            is_free=False,
            unlock_type=DramaEpisode.UNLOCK_MEOW_POINTS,
            meow_points_price=30,
            meow_credit_price=7,
            is_active=True,
        )

    def test_points_unlock_success(self):
        MeowPointWallet.objects.create(user=self.user, balance=100)
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse('drama-episode-unlock', args=[self.episode.id]),
            {'payment_method': 'meow_points'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['payment_method'], 'meow_points')
        self.assertEqual(response.data['points_charged'], 30)
        wallet = MeowPointWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 70)
        unlock = DramaUnlock.objects.get(user=self.user, episode=self.episode)
        self.assertEqual(unlock.source, DramaUnlock.SOURCE_MEOW_POINTS)
        self.assertEqual(unlock.points_amount, 30)

    def test_credit_unlock_success(self):
        MeowCreditWallet.objects.create(user=self.user, balance=20)
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse('drama-episode-unlock', args=[self.episode.id]),
            {'payment_method': 'meow_credit'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['payment_method'], 'meow_credit')
        self.assertEqual(response.data['credits_charged'], 7)
        wallet = MeowCreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 13)
        unlock = DramaUnlock.objects.get(user=self.user, episode=self.episode)
        self.assertEqual(unlock.source, DramaUnlock.SOURCE_MEOW_CREDIT)
        self.assertEqual(unlock.credit_amount, 7)
        self.assertTrue(MeowCreditLedger.objects.filter(user=self.user, target_type='drama_episode', target_id=self.episode.id).exists())

    def test_credit_unlock_insufficient_balance(self):
        MeowCreditWallet.objects.create(user=self.user, balance=3)
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse('drama-episode-unlock', args=[self.episode.id]),
            {'payment_method': 'meow_credit'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'insufficient_balance')
        self.assertFalse(DramaUnlock.objects.filter(user=self.user, episode=self.episode).exists())

    def test_repeat_unlock_does_not_charge_again(self):
        MeowCreditWallet.objects.create(user=self.user, balance=20)
        self.client.force_authenticate(user=self.user)
        first = self.client.post(reverse('drama-episode-unlock', args=[self.episode.id]), {'payment_method': 'meow_credit'}, format='json')
        second = self.client.post(reverse('drama-episode-unlock', args=[self.episode.id]), {'payment_method': 'meow_credit'}, format='json')

        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data['code'], 'already_unlocked')
        self.assertEqual(second.data['credits_charged'], 0)
        wallet = MeowCreditWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 13)
        self.assertEqual(MeowCreditLedger.objects.filter(user=self.user, target_type='drama_episode', target_id=self.episode.id).count(), 1)

    def test_legacy_empty_request_body_defaults_to_points(self):
        MeowPointWallet.objects.create(user=self.user, balance=100)
        self.client.force_authenticate(user=self.user)

        response = self.client.post(reverse('drama-episode-unlock', args=[self.episode.id]), {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['payment_method'], 'meow_points')
        self.assertEqual(response.data['points_charged'], 30)
        wallet = MeowPointWallet.objects.get(user=self.user)
        self.assertEqual(wallet.balance, 70)

    def test_invalid_payment_method(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.post(
            reverse('drama-episode-unlock', args=[self.episode.id]),
            {'payment_method': 'cash'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'invalid_payment_method')


class DramaViewTrackingAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='viewer@example.com', password='pass1234')
        self.series = DramaSeries.objects.create(title='Tracked', status=DramaSeries.STATUS_PUBLISHED, is_active=True)
        self.inactive_series = DramaSeries.objects.create(title='Inactive', status=DramaSeries.STATUS_DRAFT, is_active=False)

    def test_first_view_increments_count(self):
        response = self.client.post(reverse('drama-series-view-track', args=[self.series.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['counted'])
        self.series.refresh_from_db()
        self.assertEqual(self.series.view_count, 1)

    def test_duplicate_authenticated_view_within_24h_not_incremented(self):
        self.client.force_authenticate(self.user)
        first = self.client.post(reverse('drama-series-view-track', args=[self.series.id]), format='json')
        second = self.client.post(reverse('drama-series-view-track', args=[self.series.id]), format='json')
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertFalse(second.data['counted'])
        self.series.refresh_from_db()
        self.assertEqual(self.series.view_count, 1)

    def test_anonymous_view_works(self):
        response = self.client.post(reverse('drama-series-view-track', args=[self.series.id]), format='json', REMOTE_ADDR='1.2.3.4')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['counted'])

    def test_inactive_or_draft_not_counted(self):
        response = self.client.post(reverse('drama-series-view-track', args=[self.inactive_series.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_and_detail_unchanged(self):
        list_response = self.client.get(reverse('drama-series-list'))
        detail_response = self.client.get(reverse('drama-series-detail', args=[self.series.id]))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)



class DramaGiftAPITestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='drama-gift-owner@example.com', password='pass1234')
        self.sender = User.objects.create_user(email='drama-gift-sender@example.com', password='pass1234')
        self.series = DramaSeries.objects.create(
            owner=self.owner,
            title='Giftable Drama',
            status=DramaSeries.STATUS_PUBLISHED,
            is_active=True,
        )
        self.ownerless_series = DramaSeries.objects.create(
            title='Ownerless Drama',
            status=DramaSeries.STATUS_PUBLISHED,
            is_active=True,
        )
        self.active_gift = Gift.objects.create(code='rose', name='Rose', points_price=10, is_active=True)
        self.inactive_gift = Gift.objects.create(code='old', name='Old', points_price=10, is_active=False)

    def test_drama_gift_send_success(self):
        MeowPointService.add_points(user=self.sender, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('drama-gift-send', args=[self.series.id]),
            {'gift_code': 'rose', 'quantity': 2},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['drama_series_id'], self.series.id)
        wallet = MeowPointWallet.objects.get(user=self.sender)
        self.assertEqual(wallet.balance, 80)
        tx = GiftTransaction.objects.get(sender=self.sender, drama_series=self.series)
        self.assertEqual(tx.receiver, self.owner)
        self.assertIsNone(tx.video)
        self.assertIsNone(tx.stream)
        self.assertEqual(tx.total_points, 20)

    def test_drama_gift_insufficient_balance(self):
        MeowPointService.add_points(user=self.sender, amount=5, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('drama-gift-send', args=[self.series.id]),
            {'gift_code': 'rose', 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'insufficient_balance')
        self.assertFalse(GiftTransaction.objects.filter(drama_series=self.series).exists())

    def test_ownerless_drama_gift_returns_clear_error(self):
        MeowPointService.add_points(user=self.sender, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('drama-gift-send', args=[self.ownerless_series.id]),
            {'gift_code': 'rose', 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['code'], 'drama_owner_required')
        self.assertEqual(response.data['detail'], 'Drama series has no owner to receive gifts.')

    def test_inactive_drama_gift_cannot_be_sent(self):
        MeowPointService.add_points(user=self.sender, amount=100, entry_type=MeowPointLedger.TYPE_PURCHASE)
        self.client.force_authenticate(user=self.sender)

        response = self.client.post(
            reverse('drama-gift-send', args=[self.series.id]),
            {'gift_code': 'old', 'quantity': 1},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Gift is not active.')
        self.assertFalse(GiftTransaction.objects.filter(drama_series=self.series).exists())
