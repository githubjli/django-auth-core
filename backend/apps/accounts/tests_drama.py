from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import DramaEpisode, DramaSeries


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
