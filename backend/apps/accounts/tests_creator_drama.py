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


    def test_series_serializer_exposes_interaction_counts(self):
        self.own_series.comment_count = 4
        self.own_series.share_count = 5
        self.own_series.gift_count = 2
        self.own_series.gift_amount_total = 60
        self.own_series.save(update_fields=['comment_count', 'share_count', 'gift_count', 'gift_amount_total'])
        self.creator.subscriber_count = 6
        self.creator.save(update_fields=['subscriber_count'])
        self.client.force_authenticate(self.creator)

        response = self.client.get(f'/api/creator/dramas/{self.own_series.id}/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['comment_count'], 4)
        self.assertEqual(response.data['share_count'], 5)
        self.assertEqual(response.data['gift_count'], 2)
        self.assertEqual(response.data['gift_amount_total'], 60)
        self.assertEqual(response.data['subscriber_count'], 6)

    def test_creator_can_create_and_update_credit_price(self):
        self.client.force_authenticate(self.creator)
        create_response = self.client.post(
            f'/api/creator/dramas/{self.own_series.id}/episodes/',
            {
                'episode_no': 10,
                'title': 'Credit Ep',
                'unlock_type': 'meow_points',
                'meow_points_price': 30,
                'credits_price': 8,
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data['meow_credit_price'], 8)
        self.assertEqual(create_response.data['credits_price'], 8)
        episode = DramaEpisode.objects.get(pk=create_response.data['id'])
        self.assertEqual(episode.meow_credit_price, 8)

        update_response = self.client.patch(
            f'/api/creator/dramas/{self.own_series.id}/episodes/{episode.id}/',
            {'credits_price': 12},
            format='json',
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertEqual(update_response.data['meow_credit_price'], 12)
        self.assertEqual(update_response.data['credits_price'], 12)
        episode.refresh_from_db()
        self.assertEqual(episode.meow_credit_price, 12)


        priority_response = self.client.patch(
            f'/api/creator/dramas/{self.own_series.id}/episodes/{episode.id}/',
            {'meow_credit_price': 14, 'credits_price': 99},
            format='json',
        )

        self.assertEqual(priority_response.status_code, status.HTTP_200_OK)
        self.assertEqual(priority_response.data['meow_credit_price'], 14)
        self.assertEqual(priority_response.data['credits_price'], 14)
        episode.refresh_from_db()
        self.assertEqual(episode.meow_credit_price, 14)

    def test_free_unlock_zeroes_points_and_credit_price(self):
        self.client.force_authenticate(self.creator)

        response = self.client.post(
            f'/api/creator/dramas/{self.own_series.id}/episodes/',
            {
                'episode_no': 11,
                'title': 'Free Ep',
                'unlock_type': 'free',
                'meow_points_price': 30,
                'meow_credit_price': 8,
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['meow_points_price'], 0)
        self.assertEqual(response.data['meow_credit_price'], 0)
        self.assertEqual(response.data['credits_price'], 0)
        episode = DramaEpisode.objects.get(pk=response.data['id'])
        self.assertTrue(episode.is_free)
        self.assertEqual(episode.meow_points_price, 0)
        self.assertEqual(episode.meow_credit_price, 0)
