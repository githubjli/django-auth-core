from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import ChannelSubscription, DramaSeries, GiftTransaction, LiveStream, Video, VideoLike, VideoView


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

    def _assert_public_user_summary_fields(self, item, expected_user, *, expected_is_creator):
        required_fields = {
            'id',
            'display_name',
            'nickname',
            'username',
            'avatar_url',
            'avatar',
            'bio',
            'description',
            'is_creator',
            'follower_count',
            'followers_count',
            'viewer_is_following',
        }
        self.assertTrue(required_fields.issubset(item.keys()))
        self.assertEqual(item['id'], expected_user.id)
        self.assertEqual(item['display_name'], item['nickname'])
        self.assertEqual(item['display_name'], item['username'])
        self.assertEqual(item['avatar_url'], item['avatar'])
        self.assertEqual(item['bio'], expected_user.bio)
        self.assertEqual(item['description'], expected_user.bio)
        self.assertEqual(item['is_creator'], expected_is_creator)
        self.assertEqual(item['follower_count'], item['followers_count'])

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
        self.assertEqual(response.data['email'], self.non_creator.email)

    def test_public_user_followers_returns_creator_followers(self):
        ChannelSubscription.objects.create(channel=self.creator, subscriber=self.viewer)

        response = self.client.get(reverse('public-user-followers', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.viewer.id)
        self._assert_public_user_summary_fields(response.data['results'][0], self.viewer, expected_is_creator=False)

    def test_public_user_followers_returns_non_creator_followers(self):
        ChannelSubscription.objects.create(channel=self.non_creator, subscriber=self.viewer)

        response = self.client.get(reverse('public-user-followers', kwargs={'user_id': self.non_creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.viewer.id)
        self._assert_public_user_summary_fields(response.data['results'][0], self.viewer, expected_is_creator=False)

    def test_public_user_following_returns_creator_following(self):
        ChannelSubscription.objects.create(channel=self.non_creator, subscriber=self.creator)

        response = self.client.get(reverse('public-user-following', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.non_creator.id)
        self._assert_public_user_summary_fields(response.data['results'][0], self.non_creator, expected_is_creator=False)

    def test_public_user_following_returns_non_creator_following(self):
        ChannelSubscription.objects.create(channel=self.creator, subscriber=self.non_creator)

        response = self.client.get(reverse('public-user-following', kwargs={'user_id': self.non_creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], self.creator.id)
        self._assert_public_user_summary_fields(response.data['results'][0], self.creator, expected_is_creator=True)


    def test_public_user_followers_marks_viewer_is_following_from_same_follow_table(self):
        follower = User.objects.create_user(
            email='followed-follower@example.com',
            password='pass1234',
            first_name='Followed',
            last_name='Follower',
            is_creator=True,
        )
        ChannelSubscription.objects.create(channel=self.creator, subscriber=follower)
        ChannelSubscription.objects.create(channel=follower, subscriber=self.viewer)
        self.client.force_authenticate(user=self.viewer)

        response = self.client.get(reverse('public-user-followers', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data['results'][0]
        self._assert_public_user_summary_fields(item, follower, expected_is_creator=True)
        self.assertTrue(item['viewer_is_following'])
        self.assertEqual(item['follower_count'], 1)

    def test_public_user_detail_non_creator_returns_zero_public_stats(self):
        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.non_creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['is_creator'])
        self.assertEqual(response.data['follower_count'], 0)
        self.assertEqual(response.data['following_count'], 0)
        self.assertFalse(response.data['viewer_is_following'])
        self.assertEqual(response.data['video_count'], 0)
        self.assertEqual(response.data['drama_count'], 0)
        self.assertEqual(response.data['live_count'], 0)
        self.assertEqual(response.data['total_views'], 0)
        self.assertEqual(response.data['total_likes'], 0)
        self.assertEqual(response.data['total_gifts'], 0)

    def test_public_user_detail_creator_returns_unified_public_stats(self):
        followers = [User.objects.create_user(email=f'follower-{idx}@example.com', password='pass1234') for idx in range(5)]
        for follower in followers:
            ChannelSubscription.objects.create(channel=self.creator, subscriber=follower)

        videos = [self._create_video(owner=self.creator, title=f'published-{idx}') for idx in range(8)]
        self._create_video(owner=self.creator, title='private', visibility=Video.VISIBILITY_PRIVATE)
        self._create_video(owner=self.creator, title='inactive', status_value=Video.STATUS_ARCHIVED)
        for idx in range(9):
            VideoView.objects.create(video=videos[idx % len(videos)], viewer=None)
        likers = [User.objects.create_user(email=f'liker-{idx}@example.com', password='pass1234') for idx in range(7)]
        for idx, liker in enumerate(likers):
            VideoLike.objects.create(video=videos[idx % len(videos)], user=liker)
        GiftTransaction.objects.create(
            sender=self.viewer,
            receiver=self.creator,
            video=videos[0],
            target_type=GiftTransaction.TARGET_VIDEO,
            target_id=videos[0].id,
            amount=51,
        )

        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.creator.email)
        self.assertTrue(response.data['is_creator'])
        self.assertEqual(response.data['follower_count'], 5)
        self.assertEqual(response.data['followers_count'], 5)
        self.assertEqual(response.data['following_count'], 0)
        self.assertFalse(response.data['viewer_is_following'])
        self.assertEqual(response.data['video_count'], 8)
        self.assertEqual(response.data['video_total_views'], 9)
        self.assertEqual(response.data['total_views'], 9)
        self.assertEqual(response.data['video_total_likes'], 7)
        self.assertEqual(response.data['total_likes'], 7)
        self.assertEqual(response.data['total_gifts'], 51)
        self.assertEqual(response.data['view_count'], response.data['total_views'])
        self.assertEqual(response.data['like_count'], response.data['total_likes'])

    def test_public_user_detail_viewer_is_following_for_authenticated_viewer(self):
        ChannelSubscription.objects.create(channel=self.creator, subscriber=self.viewer)
        self.client.force_authenticate(user=self.viewer)

        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['viewer_is_following'])


    def test_public_user_detail_non_creator_returns_zero_public_stats(self):
        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.non_creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['is_creator'])
        self.assertEqual(response.data['follower_count'], 0)
        self.assertEqual(response.data['following_count'], 0)
        self.assertFalse(response.data['viewer_is_following'])
        self.assertEqual(response.data['video_count'], 0)
        self.assertEqual(response.data['drama_count'], 0)
        self.assertEqual(response.data['live_count'], 0)
        self.assertEqual(response.data['total_views'], 0)
        self.assertEqual(response.data['total_likes'], 0)
        self.assertEqual(response.data['total_gifts'], 0)

    def test_public_user_detail_creator_returns_unified_public_stats(self):
        followers = [User.objects.create_user(email=f'follower-{idx}@example.com', password='pass1234') for idx in range(5)]
        for follower in followers:
            ChannelSubscription.objects.create(channel=self.creator, subscriber=follower)

        videos = [self._create_video(owner=self.creator, title=f'published-{idx}') for idx in range(8)]
        self._create_video(owner=self.creator, title='private', visibility=Video.VISIBILITY_PRIVATE)
        self._create_video(owner=self.creator, title='inactive', status_value=Video.STATUS_ARCHIVED)
        for idx in range(9):
            VideoView.objects.create(video=videos[idx % len(videos)], viewer=None)
        likers = [User.objects.create_user(email=f'liker-{idx}@example.com', password='pass1234') for idx in range(7)]
        for idx, liker in enumerate(likers):
            VideoLike.objects.create(video=videos[idx % len(videos)], user=liker)
        GiftTransaction.objects.create(
            sender=self.viewer,
            receiver=self.creator,
            video=videos[0],
            target_type=GiftTransaction.TARGET_VIDEO,
            target_id=videos[0].id,
            amount=51,
        )

        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], self.creator.email)
        self.assertTrue(response.data['is_creator'])
        self.assertEqual(response.data['follower_count'], 5)
        self.assertEqual(response.data['followers_count'], 5)
        self.assertEqual(response.data['following_count'], 0)
        self.assertFalse(response.data['viewer_is_following'])
        self.assertEqual(response.data['video_count'], 8)
        self.assertEqual(response.data['video_total_views'], 9)
        self.assertEqual(response.data['total_views'], 9)
        self.assertEqual(response.data['video_total_likes'], 7)
        self.assertEqual(response.data['total_likes'], 7)
        self.assertEqual(response.data['total_gifts'], 51)
        self.assertEqual(response.data['view_count'], response.data['total_views'])
        self.assertEqual(response.data['like_count'], response.data['total_likes'])

    def test_public_user_detail_viewer_is_following_for_authenticated_viewer(self):
        ChannelSubscription.objects.create(channel=self.creator, subscriber=self.viewer)
        self.client.force_authenticate(user=self.viewer)

        response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['viewer_is_following'])

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

    def test_creator_detail_video_count_matches_public_active_video_list_count(self):
        self._create_video(owner=self.creator, title='active-1')
        self._create_video(owner=self.creator, title='active-2')
        self._create_video(owner=self.creator, title='private', visibility=Video.VISIBILITY_PRIVATE)
        self._create_video(owner=self.creator, title='flagged', status_value=Video.STATUS_FLAGGED)

        detail_response = self.client.get(reverse('public-creator-detail', kwargs={'creator_id': self.creator.id}))
        videos_response = self.client.get(reverse('public-creator-videos', kwargs={'creator_id': self.creator.id}))

        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(videos_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['video_count'], 2)
        self.assertEqual(detail_response.data['video_count'], videos_response.data['count'])
        self.assertEqual(len(videos_response.data['results']), 2)

    def test_creator_detail_totals_count_public_active_video_views_and_likes_only(self):
        active_one = self._create_video(owner=self.creator, title='active-1')
        active_two = self._create_video(owner=self.creator, title='active-2')
        private_video = self._create_video(owner=self.creator, title='private', visibility=Video.VISIBILITY_PRIVATE)
        flagged_video = self._create_video(owner=self.creator, title='flagged', status_value=Video.STATUS_FLAGGED)

        Video.objects.filter(pk=active_one.pk).update(like_count=2)
        Video.objects.filter(pk=active_two.pk).update(like_count=1)
        Video.objects.filter(pk=private_video.pk).update(like_count=4)
        Video.objects.filter(pk=flagged_video.pk).update(like_count=8)
        VideoLike.objects.create(video=active_one, user=self.viewer)
        VideoLike.objects.create(video=active_one, user=self.non_creator)
        VideoLike.objects.create(video=active_two, user=self.creator)
        VideoLike.objects.create(video=private_video, user=self.viewer)
        VideoLike.objects.create(video=flagged_video, user=self.viewer)
        VideoView.objects.create(video=active_one, viewer=self.viewer)
        VideoView.objects.create(video=active_one, viewer=None)
        VideoView.objects.create(video=active_two, viewer=self.viewer)
        VideoView.objects.create(video=private_video, viewer=self.viewer)
        VideoView.objects.create(video=flagged_video, viewer=self.viewer)

        response = self.client.get(reverse('public-creator-detail', kwargs={'creator_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_views'], 3)
        self.assertEqual(response.data['view_count'], 3)
        self.assertEqual(response.data['like_count'], 3)
        self.assertEqual(response.data['total_likes'], 3)


    def test_account_profile_and_public_creator_profile_share_content_aggregates(self):
        active_video = self._create_video(owner=self.creator, title='active-aggregate')
        private_video = self._create_video(
            owner=self.creator,
            title='private-aggregate',
            visibility=Video.VISIBILITY_PRIVATE,
        )
        inactive_video = self._create_video(
            owner=self.creator,
            title='inactive-aggregate',
            status_value=Video.STATUS_ARCHIVED,
        )
        VideoView.objects.create(video=active_video, viewer=self.viewer)
        VideoView.objects.create(video=active_video, viewer=None)
        VideoView.objects.create(video=private_video, viewer=self.viewer)
        VideoView.objects.create(video=inactive_video, viewer=self.viewer)
        VideoLike.objects.create(video=active_video, user=self.viewer)
        VideoLike.objects.create(video=private_video, user=self.viewer)
        VideoLike.objects.create(video=inactive_video, user=self.viewer)
        published_drama = DramaSeries.objects.create(
            owner=self.creator,
            title='published-aggregate',
            is_active=True,
            status=DramaSeries.STATUS_PUBLISHED,
            view_count=5,
        )
        DramaSeries.objects.create(
            owner=self.creator,
            title='draft-aggregate',
            is_active=True,
            status=DramaSeries.STATUS_DRAFT,
            view_count=7,
        )
        DramaSeries.objects.create(
            owner=self.creator,
            title='inactive-drama-aggregate',
            is_active=False,
            status=DramaSeries.STATUS_PUBLISHED,
            view_count=11,
        )
        LiveStream.objects.create(
            owner=self.creator,
            title='public-live-aggregate',
            visibility=LiveStream.VISIBILITY_PUBLIC,
        )
        LiveStream.objects.create(
            owner=self.creator,
            title='unlisted-live-aggregate',
            visibility=LiveStream.VISIBILITY_UNLISTED,
        )
        LiveStream.objects.create(
            owner=self.creator,
            title='private-live-aggregate',
            visibility=LiveStream.VISIBILITY_PRIVATE,
        )

        public_response = self.client.get(reverse('public-creator-detail', kwargs={'creator_id': self.creator.id}))
        self.client.force_authenticate(user=self.creator)
        profile_response = self.client.get(reverse('account-profile'))
        video_detail_response = self.client.get(reverse('public-video-detail', kwargs={'pk': active_video.pk}))

        self.assertEqual(public_response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile_response.status_code, status.HTTP_200_OK)
        self.assertEqual(video_detail_response.status_code, status.HTTP_200_OK)
        expected = {
            'video_count': 1,
            'drama_count': 1,
            'live_count': 2,
            'video_total_views': 2,
            'drama_total_views': published_drama.view_count,
            'live_total_views': 0,
            'total_views': 7,
            'view_count': 7,
            'video_total_likes': 1,
            'drama_total_likes': 0,
            'live_total_likes': 0,
            'total_likes': 1,
            'like_count': 1,
        }
        aggregate_fields = set(expected)
        self.assertTrue(aggregate_fields.issubset(public_response.data.keys()))
        self.assertTrue(aggregate_fields.issubset(profile_response.data.keys()))
        for key, value in expected.items():
            self.assertEqual(public_response.data[key], value, key)
            self.assertEqual(profile_response.data[key], value, key)

        self.assertEqual(
            public_response.data['total_views'],
            public_response.data['video_total_views']
            + public_response.data['drama_total_views']
            + public_response.data['live_total_views'],
        )
        self.assertEqual(
            profile_response.data['total_views'],
            profile_response.data['video_total_views']
            + profile_response.data['drama_total_views']
            + profile_response.data['live_total_views'],
        )
        self.assertEqual(video_detail_response.data['view_count'], 2)
        self.assertNotEqual(video_detail_response.data['view_count'], profile_response.data['view_count'])

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

class PublicVideoCreatorPayloadTestCase(APITestCase):
    def setUp(self):
        self.creator = User.objects.create_user(
            email='video-creator@example.com',
            password='pass1234',
            first_name='Video',
            last_name='Creator',
            is_creator=True,
        )
        self.viewer = User.objects.create_user(email='video-viewer@example.com', password='pass1234')
        self.video = Video.objects.create(
            owner=self.creator,
            title='creator payload video',
            visibility=Video.VISIBILITY_PUBLIC,
            status=Video.STATUS_ACTIVE,
        )

    def test_public_video_detail_returns_creator_id_and_consistent_follow_counts_for_anonymous(self):
        for idx in range(5):
            follower = User.objects.create_user(email=f'video-follower-{idx}@example.com', password='pass1234')
            ChannelSubscription.objects.create(channel=self.creator, subscriber=follower)

        response = self.client.get(reverse('public-video-detail', kwargs={'pk': self.video.id}))
        profile_response = self.client.get(reverse('public-user-detail', kwargs={'user_id': self.creator.id}))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile_response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['creator']['id'], self.creator.id)
        self.assertEqual(response.data['owner_id'], self.creator.id)
        self.assertEqual(response.data['creator']['name'], self.creator.display_name)
        self.assertEqual(response.data['owner_name'], self.creator.display_name)
        self.assertEqual(response.data['creator']['avatar_url'], response.data['owner_avatar_url'])
        self.assertEqual(response.data['creator']['follower_count'], 5)
        self.assertEqual(response.data['creator']['subscriber_count'], 5)
        self.assertEqual(response.data['owner_follower_count'], 5)
        self.assertEqual(response.data['owner_subscriber_count'], 5)
        self.assertEqual(profile_response.data['follower_count'], 5)
        self.assertFalse(response.data['creator']['is_following'])
        self.assertFalse(response.data['is_following_owner'])
        self.assertFalse(response.data['is_liked'])

    def test_public_video_detail_following_and_like_state_for_authenticated_viewer(self):
        self.client.force_authenticate(user=self.viewer)

        follow_response = self.client.post(reverse('public-user-follow', kwargs={'user_id': self.creator.id}))
        like_response = self.client.post(reverse('public-video-like', kwargs={'pk': self.video.id}))
        detail_response = self.client.get(reverse('public-video-detail', kwargs={'pk': self.video.id}))

        self.assertEqual(follow_response.status_code, status.HTTP_200_OK)
        self.assertEqual(follow_response.data['follower_count'], 1)
        self.assertEqual(like_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertTrue(detail_response.data['creator']['is_following'])
        self.assertTrue(detail_response.data['is_following_owner'])
        self.assertTrue(detail_response.data['is_liked'])
        self.assertEqual(detail_response.data['like_count'], 1)

    def test_public_video_recommendations_include_creator_owner_payload(self):
        ChannelSubscription.objects.create(channel=self.creator, subscriber=self.viewer)
        recommended = Video.objects.create(
            owner=self.creator,
            title='recommended payload video',
            visibility=Video.VISIBILITY_PUBLIC,
            status=Video.STATUS_ACTIVE,
        )
        self.client.force_authenticate(user=self.viewer)

        response = self.client.get(reverse('public-video-recommendations', kwargs={'pk': self.video.id}), {'limit': 1})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        item = response.data[0]
        self.assertEqual(item['id'], recommended.id)
        self.assertEqual(item['creator']['id'], self.creator.id)
        self.assertEqual(item['owner_id'], self.creator.id)
        self.assertEqual(item['creator']['follower_count'], 1)
        self.assertEqual(item['creator']['subscriber_count'], 1)
        self.assertEqual(item['owner_follower_count'], 1)
        self.assertEqual(item['owner_subscriber_count'], 1)
        self.assertTrue(item['creator']['is_following'])
        self.assertTrue(item['is_following_owner'])
