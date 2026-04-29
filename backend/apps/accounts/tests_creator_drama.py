from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import DramaEpisode, DramaSeries, User


class CreatorDramaAPITestCase(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(email='creator@example.com', password='pass1234', is_creator=True)
        self.other_creator = User.objects.create_user(email='creator2@example.com', password='pass1234', is_creator=True)
        self.viewer = User.objects.create_user(email='viewer@example.com', password='pass1234', is_creator=False)

        self.own_series = DramaSeries.objects.create(owner=self.creator, title='Own', status=DramaSeries.STATUS_PUBLISHED, is_active=True)
        self.other_series = DramaSeries.objects.create(owner=self.other_creator, title='Other', status=DramaSeries.STATUS_PUBLISHED, is_active=True)

    def test_unauthenticated_forbidden(self):
        response = self.client.get('/api/creator/dramas/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_creator_forbidden(self):
        self.client.force_authenticate(self.viewer)
        response = self.client.get('/api/creator/dramas/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_creator_create_and_owner_assignment(self):
        self.client.force_authenticate(self.creator)
        response = self.client.post('/api/creator/dramas/', {'title': 'New Drama', 'tags': ['a', 'b']}, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = DramaSeries.objects.get(id=response.data['id'])
        self.assertEqual(created.owner_id, self.creator.id)

    def test_creator_list_scoped(self):
        self.client.force_authenticate(self.creator)
        response = self.client.get('/api/creator/dramas/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.data['results'] if isinstance(response.data, dict) else response.data
        ids = {item['id'] for item in items}
        self.assertIn(self.own_series.id, ids)
        self.assertNotIn(self.other_series.id, ids)

    def test_creator_cannot_manage_other_creator_series(self):
        self.client.force_authenticate(self.creator)
        response = self.client.patch(f'/api/creator/dramas/{self.other_series.id}/', {'title': 'x'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_series_soft_delete_hidden_public(self):
        self.client.force_authenticate(self.creator)
        del_resp = self.client.delete(f'/api/creator/dramas/{self.own_series.id}/')
        self.assertEqual(del_resp.status_code, status.HTTP_204_NO_CONTENT)
        list_resp = self.client.get(reverse('drama-series-list'))
        ids = {item['id'] for item in list_resp.data['results']}
        self.assertNotIn(self.own_series.id, ids)

    def test_episode_create_duplicate_and_soft_delete(self):
        self.client.force_authenticate(self.creator)
        create1 = self.client.post(
            f'/api/creator/dramas/{self.own_series.id}/episodes/',
            {'episode_no': 1, 'title': 'Ep1', 'unlock_type': 'meow_points', 'meow_points_price': 10},
            format='json',
        )
        self.assertEqual(create1.status_code, status.HTTP_201_CREATED)

        create2 = self.client.post(
            f'/api/creator/dramas/{self.own_series.id}/episodes/',
            {'episode_no': 1, 'title': 'Dup', 'unlock_type': 'meow_points', 'meow_points_price': 10},
            format='json',
        )
        self.assertEqual(create2.status_code, status.HTTP_400_BAD_REQUEST)

        ep_id = create1.data['id']
        del_resp = self.client.delete(f'/api/creator/dramas/{self.own_series.id}/episodes/{ep_id}/')
        self.assertEqual(del_resp.status_code, status.HTTP_204_NO_CONTENT)

    def test_locked_episode_still_hides_playback(self):
        episode = DramaEpisode.objects.create(
            series=self.own_series,
            episode_no=1,
            title='Locked',
            is_free=False,
            unlock_type=DramaEpisode.UNLOCK_MEOW_POINTS,
            meow_points_price=30,
            hls_url='https://cdn.example.com/locked.m3u8',
            is_active=True,
        )
        response = self.client.get(reverse('drama-episode-list', args=[self.own_series.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = next(i for i in response.data['episodes'] if i['id'] == episode.id)
        self.assertIsNone(item['playback_url'])
