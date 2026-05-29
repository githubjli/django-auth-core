from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import ChannelSubscription, DramaSeries, LiveStream, Video


User = get_user_model()


class PublicVideoStatusFilterTestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='owner@example.com', password='pass1234')

    def _create_video(self, title, status_value):
        return Video.objects.create(
            owner=self.owner,
            title=title,
            visibility=Video.VISIBILITY_PUBLIC,
            status=status_value,
        )

    def test_public_video_list_excludes_non_active(self):
        active_video = self._create_video('active', Video.STATUS_ACTIVE)
        self._create_video('flagged', Video.STATUS_FLAGGED)
        self._create_video('archived', Video.STATUS_ARCHIVED)

        response = self.client.get(reverse('public-video-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in response.data['results']]
        self.assertIn(active_video.id, ids)
        self.assertEqual(len(ids), 1)

    def test_public_video_detail_returns_404_for_non_active(self):
        flagged_video = self._create_video('flagged', Video.STATUS_FLAGGED)

        response = self.client.get(reverse('public-video-detail', kwargs={'pk': flagged_video.id}))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_related_excludes_non_active(self):
        anchor = self._create_video('anchor', Video.STATUS_ACTIVE)
        related_active = self._create_video('related-active', Video.STATUS_ACTIVE)
        self._create_video('related-flagged', Video.STATUS_FLAGGED)

        response = self.client.get(reverse('public-video-related', kwargs={'pk': anchor.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in response.data]
        self.assertIn(related_active.id, ids)
        self.assertNotIn(anchor.id, ids)
        self.assertEqual(len(ids), 1)


class PublicCreatorAPITestCase(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            email='creator@example.com',
            password='pass1234',
            first_name='Creator',
            last_name='Name',
            is_creator=True,
        )
        self.viewer = User.objects.create_user(email='viewer@example.com', password='pass1234')
        self.non_creator = User.objects.create_user(email='noncreator@example.com', password='pass1234', is_creator=False)

    def _create_video(self, *, owner, visibility=Video.VISIBILITY_PUBLIC, status_value=Video.STATUS_ACTIVE, title='video'):
        return Video.objects.create(
            owner=owner,
            title=title,
            visibility=visibility,
            status=status_value,
        )

    def test_creator_detail_only_allows_is_creator(self):
        response = self.client.get(reverse('public-creator-detail', kwargs={'creator_id': self.non_creator.id}))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_user_detail_returns_creator_profile(self):
        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.creator.id)
        self.assertTrue(response.data['is_creator'])
        self.assertIn('display_name', response.data)
        self.assertIn('nickname', response.data)
        self.assertIn('followers_count', response.data)
        self.assertIn('contents', response.data)

    def test_public_user_detail_returns_non_creator_profile(self):
        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.non_creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['id'], self.non_creator.id)
        self.assertFalse(response.data['is_creator'])
        self.assertEqual(response.data['contents'], [])
        self.assertEqual(response.data['posts'], [])
        self.assertEqual(response.data['works'], [])

    def test_public_user_detail_returns_404_for_missing_user(self):
        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': 999999}))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_user_detail_excludes_sensitive_fields(self):
        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.non_creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        sensitive_fields = {
            'email',
            'phone',
            'first_name',
            'last_name',
            'is_staff',
            'is_superuser',
            'is_active',
            'password',
            'linked_wallet_id',
            'primary_user_address',
            'wallet_link_status',
        }
        self.assertTrue(sensitive_fields.isdisjoint(response.data.keys()))
        self.assertNotIn(self.non_creator.email, str(response.data))

    def test_public_user_followers_returns_creator_followers(self):
        ChannelSubscription.objects.create(channel=self.creator, subscriber=self.viewer)

        response = self.client.get(reverse('public-user-followers', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.viewer.id)

    def test_public_user_followers_returns_non_creator_followers(self):
        ChannelSubscription.objects.create(channel=self.non_creator, subscriber=self.viewer)

        response = self.client.get(reverse('public-user-followers', kwargs={'user_id': self.non_creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.viewer.id)

    def test_public_user_following_returns_creator_following(self):
        ChannelSubscription.objects.create(channel=self.non_creator, subscriber=self.creator)

        response = self.client.get(reverse('public-user-following', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.non_creator.id)

    def test_public_user_following_returns_non_creator_following(self):
        ChannelSubscription.objects.create(channel=self.creator, subscriber=self.non_creator)

        response = self.client.get(reverse('public-user-following', kwargs={'user_id': self.non_creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.creator.id)

    def test_public_user_relationship_lists_return_404_for_missing_user(self):
        followers_response = self.client.get(reverse('public-user-followers', kwargs={'user_id': 999999}))
        following_response = self.client.get(reverse('public-user-following', kwargs={'user_id': 999999}))

        self.assertEqual(followers_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(following_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_user_followers_response_is_paginated(self):
        follower = User.objects.create_user(email='follower-page@example.com', password='pass1234')
        ChannelSubscription.objects.create(channel=self.creator, subscriber=follower)

        response = self.client.get(reverse('public-user-followers', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('count', response.data)
        self.assertIn('next', response.data)
        self.assertIn('previous', response.data)
        self.assertIn('results', response.data)
        self.assertIsInstance(response.data['results'], list)

    def test_public_user_relationship_list_excludes_sensitive_fields(self):
        ChannelSubscription.objects.create(channel=self.creator, subscriber=self.viewer)

        response = self.client.get(reverse('public-user-followers', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data['results'][0]
        sensitive_fields = {
            'email',
            'phone',
            'real_name',
            'password',
            'permission',
            'role',
            'is_staff',
            'is_superuser',
            'is_active',
            'last_login',
            'date_joined',
        }
        self.assertTrue(sensitive_fields.isdisjoint(item.keys()))
        self.assertNotIn(self.viewer.email, str(item))

    def test_creator_detail_video_count_counts_public_active_only(self):
        self._create_video(owner=self.creator, title='active-1')
        self._create_video(owner=self.creator, title='active-2')
        self._create_video(owner=self.creator, title='private', visibility=Video.VISIBILITY_PRIVATE)
        self._create_video(owner=self.creator, title='flagged', status_value=Video.STATUS_FLAGGED)

        response = self.client.get(reverse('public-creator-detail', kwargs={'creator_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['video_count'], 2)

    def test_creator_videos_returns_only_creator_public_active(self):
        expected = self._create_video(owner=self.creator, title='creator-active')
        self._create_video(owner=self.creator, title='creator-archived', status_value=Video.STATUS_ARCHIVED)
        self._create_video(owner=self.creator, title='creator-private', visibility=Video.VISIBILITY_PRIVATE)
        self._create_video(owner=self.non_creator, title='other-active')

        response = self.client.get(reverse('public-creator-videos', kwargs={'creator_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in response.data['results']]
        self.assertEqual(ids, [expected.id])

    def test_creator_detail_viewer_is_following_for_authenticated_user(self):
        ChannelSubscription.objects.create(channel=self.creator, subscriber=self.viewer)
        self.client.force_authenticate(user=self.viewer)

        response = self.client.get(reverse('public-creator-detail', kwargs={'creator_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['viewer_is_following'])

    def test_creator_detail_viewer_is_following_false_for_anonymous(self):
        response = self.client.get(reverse('public-creator-detail', kwargs={'creator_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['viewer_is_following'])

    def test_creator_dramas_returns_only_public_published(self):
        published = DramaSeries.objects.create(
            owner=self.creator,
            title='published',
            is_active=True,
            status=DramaSeries.STATUS_PUBLISHED,
        )
        DramaSeries.objects.create(
            owner=self.creator,
            title='draft',
            is_active=True,
            status=DramaSeries.STATUS_DRAFT,
        )
        DramaSeries.objects.create(
            owner=self.creator,
            title='inactive',
            is_active=False,
            status=DramaSeries.STATUS_PUBLISHED,
        )
        DramaSeries.objects.create(
            owner=self.non_creator,
            title='other',
            is_active=True,
            status=DramaSeries.STATUS_PUBLISHED,
        )

        response = self.client.get(reverse('public-creator-dramas', kwargs={'creator_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in response.data['results']]
        self.assertEqual(ids, [published.id])

    def test_creator_lives_returns_only_public_or_unlisted_and_orders_live_then_ended(self):
        live_stream = LiveStream.objects.create(
            owner=self.creator,
            title='live',
            visibility=LiveStream.VISIBILITY_PUBLIC,
            status=LiveStream.STATUS_LIVE,
        )
        ended_stream = LiveStream.objects.create(
            owner=self.creator,
            title='ended',
            visibility=LiveStream.VISIBILITY_PUBLIC,
            status=LiveStream.STATUS_ENDED,
        )
        LiveStream.objects.create(
            owner=self.creator,
            title='private',
            visibility=LiveStream.VISIBILITY_PRIVATE,
            status=LiveStream.STATUS_ENDED,
        )
        LiveStream.objects.create(
            owner=self.non_creator,
            title='other',
            visibility=LiveStream.VISIBILITY_PUBLIC,
            status=LiveStream.STATUS_LIVE,
        )

        response = self.client.get(reverse('public-creator-lives', kwargs={'creator_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item['id'] for item in response.data['results']]
        self.assertEqual(ids, [live_stream.id, ended_stream.id])

    def test_creator_dramas_and_lives_return_404_for_non_creator(self):
        drama_response = self.client.get(reverse('public-creator-dramas', kwargs={'creator_id': self.non_creator.id}))
        live_response = self.client.get(reverse('public-creator-lives', kwargs={'creator_id': self.non_creator.id}))
        self.assertEqual(drama_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(live_response.status_code, status.HTTP_404_NOT_FOUND)


class PublicVideoViewTrackingTestCase(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            email='creator-view@example.com',
            password='pass1234',
            is_creator=True,
        )
        self.video = Video.objects.create(
            owner=self.creator,
            title='track me',
            visibility=Video.VISIBILITY_PUBLIC,
            status=Video.STATUS_ACTIVE,
        )

    def test_public_view_endpoint_increments_view_count_and_reflects_in_detail_and_creator_list(self):
        view_url = reverse('public-video-view', kwargs={'pk': self.video.id})
        detail_url = reverse('public-video-detail', kwargs={'pk': self.video.id})
        creator_list_url = reverse('creator-video-list-create')

        first = self.client.post(view_url)
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertIn('view_count', first.data)
        self.assertEqual(first.data['view_count'], 1)

        second = self.client.post(view_url)
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(second.data['view_count'], 2)

        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, status.HTTP_200_OK)
        self.assertEqual(detail.data['view_count'], 2)

        self.client.force_authenticate(user=self.creator)
        creator_list = self.client.get(creator_list_url)
        self.assertEqual(creator_list.status_code, status.HTTP_200_OK)
        results = creator_list.data['results']
        target = next(item for item in results if item['id'] == self.video.id)
        self.assertEqual(target['view_count'], 2)

    def test_public_view_endpoint_returns_404_for_private_video(self):
        private_video = Video.objects.create(
            owner=self.creator,
            title='private',
            visibility=Video.VISIBILITY_PRIVATE,
            status=Video.STATUS_ACTIVE,
        )
        response = self.client.post(reverse('public-video-view', kwargs={'pk': private_video.id}))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_public_view_endpoint_returns_404_for_non_active_video(self):
        archived_video = Video.objects.create(
            owner=self.creator,
            title='archived',
            visibility=Video.VISIBILITY_PUBLIC,
            status=Video.STATUS_ARCHIVED,
        )
        flagged_video = Video.objects.create(
            owner=self.creator,
            title='flagged',
            visibility=Video.VISIBILITY_PUBLIC,
            status=Video.STATUS_FLAGGED,
        )
        archived_response = self.client.post(reverse('public-video-view', kwargs={'pk': archived_video.id}))
        flagged_response = self.client.post(reverse('public-video-view', kwargs={'pk': flagged_video.id}))
        self.assertEqual(archived_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(flagged_response.status_code, status.HTTP_404_NOT_FOUND)
