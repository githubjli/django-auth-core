import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import Category

User = get_user_model()
TEST_MEDIA_ROOT = tempfile.mkdtemp()


class AuthAPITestCase(APITestCase):
    def create_user(self, email, password='strong-pass-123', **extra_fields):
        defaults = {
            'first_name': 'Test',
            'last_name': 'User',
        }
        defaults.update(extra_fields)
        return User.objects.create_user(email=email, password=password, **defaults)

    def test_register_login_me_and_refresh(self):
        register_response = self.client.post(
            reverse('auth-register'),
            {
                'email': 'user@example.com',
                'password': 'strong-pass-123',
                'first_name': 'Test',
                'last_name': 'User',
            },
            format='json',
        )
        self.assertEqual(register_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(register_response.data['email'], 'user@example.com')

        login_response = self.client.post(
            reverse('auth-login'),
            {
                'email': 'user@example.com',
                'password': 'strong-pass-123',
            },
            format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', login_response.data)
        self.assertIn('refresh', login_response.data)

        access = login_response.data['access']
        refresh = login_response.data['refresh']

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        me_response = self.client.get(reverse('auth-me'))
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(me_response.data['email'], 'user@example.com')

        refresh_response = self.client.post(
            reverse('auth-refresh'),
            {'refresh': refresh},
            format='json',
        )
        self.assertEqual(refresh_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh_response.data)

    def test_me_requires_authentication(self):
        response = self.client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_login_with_custom_user(self):
        user = self.create_user(
            'admin@example.com',
            first_name='Admin',
            last_name='User',
        )
        user.is_staff = True
        user.is_superuser = True
        user.save(update_fields=['is_staff', 'is_superuser'])

        login_success = self.client.login(
            email='admin@example.com',
            password='strong-pass-123',
        )
        self.assertTrue(login_success)

        response = self.client.get('/admin/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_user_management_requires_staff_or_superuser(self):
        user = self.create_user('member@example.com')
        self.client.force_authenticate(user=user)

        list_response = self.client.get(reverse('admin-user-list'))
        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)

        detail_response = self.client.get(reverse('admin-user-detail', args=[user.id]))
        self.assertEqual(detail_response.status_code, status.HTTP_403_FORBIDDEN)

        activate_response = self.client.post(reverse('admin-user-activate', args=[user.id]))
        self.assertEqual(activate_response.status_code, status.HTTP_403_FORBIDDEN)

        deactivate_response = self.client.post(reverse('admin-user-deactivate', args=[user.id]))
        self.assertEqual(deactivate_response.status_code, status.HTTP_403_FORBIDDEN)


    def test_admin_video_management_requires_staff_or_superuser(self):
        user = self.create_user('member@example.com')
        self.client.force_authenticate(user=user)

        list_response = self.client.get(reverse('admin-video-list'))
        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)

        detail_response = self.client.get(reverse('admin-video-detail', args=[1]))
        self.assertEqual(detail_response.status_code, status.HTTP_403_FORBIDDEN)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_admin_video_management_filter_update_and_delete(self):
        admin_user = self.create_user('staff@example.com', is_staff=True)
        owner = self.create_user('owner1@example.com', first_name='Owner', last_name='One')
        inactive_owner = self.create_user('owner2@example.com')
        self.client.force_authenticate(user=owner)
        first_video = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Alpha admin clip',
                'description': 'searchable body',
                'category': 'technology',
                'file': SimpleUploadedFile('alpha-admin.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data
        self.client.force_authenticate(user=inactive_owner)
        second_video = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Beta admin clip',
                'category': 'education',
                'file': SimpleUploadedFile('beta-admin.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data

        self.client.force_authenticate(user=admin_user)
        list_response = self.client.get(reverse('admin-video-list'), {'search': 'Alpha', 'owner': str(owner.id), 'category': 'technology', 'status': 'active', 'visibility': 'public'})
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data['count'], 1)
        self.assertEqual(list_response.data['results'][0]['id'], first_video['id'])
        self.assertEqual(list_response.data['results'][0]['owner_id'], owner.id)
        self.assertEqual(list_response.data['results'][0]['owner_name'], 'Owner One')
        self.assertEqual(list_response.data['results'][0]['owner_email'], 'owner1@example.com')
        self.assertEqual(list_response.data['results'][0]['status'], 'active')
        self.assertEqual(list_response.data['results'][0]['visibility'], 'public')
        self.assertEqual(list_response.data['results'][0]['like_count'], 0)
        self.assertEqual(list_response.data['results'][0]['comment_count'], 0)
        self.assertIn('updated_at', list_response.data['results'][0])

        self.client.patch(
            reverse('admin-video-detail', args=[second_video['id']]),
            {'status': 'flagged', 'visibility': 'private'},
            format='json',
        )

        inactive_list_response = self.client.get(reverse('admin-video-list'), {'status': 'flagged', 'visibility': 'private'})
        self.assertEqual(inactive_list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(inactive_list_response.data['count'], 1)
        self.assertEqual(inactive_list_response.data['results'][0]['id'], second_video['id'])

        detail_response = self.client.patch(
            reverse('admin-video-detail', args=[first_video['id']]),
            {'title': 'Admin updated title'},
            format='json',
        )
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['title'], 'Admin updated title')
        self.assertEqual(detail_response.data['owner_email'], 'owner1@example.com')

        delete_response = self.client.delete(reverse('admin-video-detail', args=[second_video['id']]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        remaining_list_response = self.client.get(reverse('admin-video-list'))
        self.assertEqual(remaining_list_response.data['count'], 1)

    def test_admin_user_management_and_activation_flow(self):
        admin_user = self.create_user('staff@example.com', is_staff=True)
        target_user = self.create_user('target@example.com')
        self.client.force_authenticate(user=admin_user)

        list_response = self.client.get(reverse('admin-user-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertTrue(
            any(item['email'] == 'target@example.com' for item in list_response.data)
        )

        detail_response = self.client.patch(
            reverse('admin-user-detail', args=[target_user.id]),
            {'first_name': 'Updated', 'last_name': 'Person'},
            format='json',
        )
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['first_name'], 'Updated')

        deactivate_response = self.client.post(reverse('admin-user-deactivate', args=[target_user.id]))
        self.assertEqual(deactivate_response.status_code, status.HTTP_200_OK)
        self.assertFalse(deactivate_response.data['is_active'])

        login_response = self.client.post(
            reverse('auth-login'),
            {'email': 'target@example.com', 'password': 'strong-pass-123'},
            format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_401_UNAUTHORIZED)

        activate_response = self.client.post(reverse('admin-user-activate', args=[target_user.id]))
        self.assertEqual(activate_response.status_code, status.HTTP_200_OK)
        self.assertTrue(activate_response.data['is_active'])

        login_response = self.client.post(
            reverse('auth-login'),
            {'email': 'target@example.com', 'password': 'strong-pass-123'},
            format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class VideoAPITestCase(APITestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def create_user(self, email, password='strong-pass-123', **extra_fields):
        return User.objects.create_user(email=email, password=password, **extra_fields)

    def authenticate(self, email='owner@example.com', password='strong-pass-123'):
        user = self.create_user(email=email, password=password)
        self.client.force_authenticate(user=user)
        return user

    def test_video_endpoints_require_authentication(self):
        list_response = self.client.get(reverse('video-list-create'))
        self.assertEqual(list_response.status_code, status.HTTP_401_UNAUTHORIZED)

        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'demo',
                'file': SimpleUploadedFile('demo.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.assertEqual(upload_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_upload_list_detail_and_delete_own_video(self):
        user = self.authenticate()
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'My first video',
                'description': 'My video description',
                'category': 'technology',
                'file': SimpleUploadedFile('first.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.assertEqual(upload_response.status_code, status.HTTP_201_CREATED)
        video_id = upload_response.data['id']
        self.assertEqual(upload_response.data['description'], 'My video description')
        self.assertEqual(upload_response.data['owner_id'], user.id)
        self.assertEqual(upload_response.data['owner_name'], 'owner@example.com')
        self.assertIsNone(upload_response.data['owner_avatar_url'])
        self.assertEqual(upload_response.data['like_count'], 0)
        self.assertEqual(upload_response.data['comment_count'], 0)
        self.assertEqual(upload_response.data['description_preview'], 'My video description')
        self.assertEqual(upload_response.data['category'], 'technology')
        self.assertTrue(upload_response.data['thumbnail'])
        self.assertIn('/media/thumbnails/', upload_response.data['thumbnail_url'])

        created_video = user.videos.get(pk=video_id)
        self.assertEqual(created_video.description, 'My video description')
        self.assertIsNotNone(created_video.category)
        self.assertEqual(created_video.category.slug, 'technology')

        list_response = self.client.get(reverse('video-list-create'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data['count'], 1)
        self.assertEqual(len(list_response.data['results']), 1)
        self.assertEqual(list_response.data['results'][0]['title'], 'My first video')
        self.assertIn('/media/thumbnails/', list_response.data['results'][0]['thumbnail_url'])

        detail_response = self.client.get(reverse('video-detail', args=[video_id]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['title'], 'My first video')
        self.assertEqual(detail_response.data['category_name'], 'Technology')
        self.assertEqual(detail_response.data['category_slug'], 'technology')
        self.assertEqual(detail_response.data['description_preview'], 'My video description')
        self.assertEqual(detail_response.data['owner_id'], user.id)
        self.assertIn('/media/videos/', detail_response.data['file_url'])
        self.assertIn('/media/thumbnails/', detail_response.data['thumbnail_url'])

        delete_response = self.client.delete(reverse('video-detail', args=[video_id]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertEqual(user.videos.count(), 0)

    def test_legacy_category_alias_is_normalized_to_canonical_slug(self):
        user = self.authenticate()
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Alias tech video',
                'category': 'tech',
                'file': SimpleUploadedFile('alias.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.assertEqual(upload_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(upload_response.data['category'], 'technology')
        self.assertEqual(upload_response.data['category_slug'], 'technology')

        created_video = user.videos.get(pk=upload_response.data['id'])
        self.assertIsNotNone(created_video.category)
        self.assertEqual(created_video.category.slug, 'technology')

    def test_user_can_only_access_own_videos(self):
        owner = self.authenticate()
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Private video',
                'category': 'education',
                'file': SimpleUploadedFile('private.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        video_id = upload_response.data['id']

        other_user = self.create_user(email='other@example.com')
        self.client.force_authenticate(user=other_user)

        list_response = self.client.get(reverse('video-list-create'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data['results'], [])

        detail_response = self.client.get(reverse('video-detail', args=[video_id]))
        self.assertEqual(detail_response.status_code, status.HTTP_404_NOT_FOUND)

        delete_response = self.client.delete(reverse('video-detail', args=[video_id]))
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertEqual(owner.videos.count(), 1)

    def test_video_list_supports_filter_search_ordering_and_pagination(self):
        self.authenticate()
        self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Zeta clip',
                'description': 'last one',
                'category': 'gaming',
                'file': SimpleUploadedFile('zeta.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Alpha tutorial',
                'description': 'first one',
                'category': 'education',
                'file': SimpleUploadedFile('alpha.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )

        category_response = self.client.get(reverse('video-list-create'), {'category': 'education'})
        self.assertEqual(category_response.status_code, status.HTTP_200_OK)
        self.assertEqual(category_response.data['count'], 1)
        self.assertEqual(category_response.data['results'][0]['title'], 'Alpha tutorial')

        search_response = self.client.get(reverse('video-list-create'), {'search': 'zeta'})
        self.assertEqual(search_response.status_code, status.HTTP_200_OK)
        self.assertEqual(search_response.data['count'], 1)
        self.assertEqual(search_response.data['results'][0]['category'], 'gaming')

        alias_filter_response = self.client.get(reverse('video-list-create'), {'category': 'tech'})
        self.assertEqual(alias_filter_response.status_code, status.HTTP_200_OK)
        self.assertEqual(alias_filter_response.data['count'], 0)

        ordered_response = self.client.get(reverse('video-list-create'), {'ordering': 'created_at'})
        self.assertEqual(ordered_response.status_code, status.HTTP_200_OK)
        self.assertEqual(ordered_response.data['results'][0]['title'], 'Zeta clip')

        paginated_response = self.client.get(reverse('video-list-create'), {'page_size': 1})
        self.assertEqual(paginated_response.status_code, status.HTTP_200_OK)
        self.assertEqual(paginated_response.data['count'], 2)
        self.assertEqual(len(paginated_response.data['results']), 1)
        self.assertIsNotNone(paginated_response.data['next'])

    def test_public_video_listing_and_detail_are_read_only(self):
        owner = self.authenticate()
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Public tech video',
                'description': 'visible to all',
                'category': 'technology',
                'file': SimpleUploadedFile('public.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        video_id = upload_response.data['id']
        self.client.force_authenticate(user=None)

        list_response = self.client.get(reverse('public-video-list'), {'search': 'tech'})
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data['count'], 1)
        self.assertEqual(list_response.data['results'][0]['title'], 'Public tech video')
        self.assertEqual(list_response.data['results'][0]['description_preview'], 'visible to all')
        self.assertIn('/media/thumbnails/', list_response.data['results'][0]['thumbnail_url'])

        detail_response = self.client.get(reverse('public-video-detail', args=[video_id]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['description'], 'visible to all')
        self.assertEqual(detail_response.data['description_preview'], 'visible to all')
        self.assertIn('/media/thumbnails/', detail_response.data['thumbnail_url'])

        create_response = self.client.post(
            reverse('public-video-list'),
            {
                'title': 'Nope',
                'file': SimpleUploadedFile('nope.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.assertEqual(create_response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        self.assertEqual(owner.videos.count(), 1)

    def test_owner_can_patch_video_metadata_and_manual_thumbnail(self):
        self.authenticate()
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Before update',
                'description': 'Old description',
                'category': 'gaming',
                'file': SimpleUploadedFile('before.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        video_id = upload_response.data['id']

        patch_response = self.client.patch(
            reverse('video-detail', args=[video_id]),
            {
                'title': 'After update',
                'description': 'New description',
                'category': 'education',
                'thumbnail': SimpleUploadedFile('manual.png', b'manual-image', content_type='image/png'),
            },
            format='multipart',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['title'], 'After update')
        self.assertEqual(patch_response.data['description'], 'New description')
        self.assertEqual(patch_response.data['category'], 'education')
        self.assertEqual(patch_response.data['category_name'], 'Education')
        self.assertEqual(patch_response.data['category_slug'], 'education')
        self.assertIn('manual', patch_response.data['thumbnail'])

    def test_owner_can_regenerate_thumbnail(self):
        self.authenticate()
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Regenerate me',
                'file': SimpleUploadedFile('regen.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        video_id = upload_response.data['id']
        original_thumbnail = upload_response.data['thumbnail']

        regenerate_response = self.client.post(
            reverse('video-regenerate-thumbnail', args=[video_id]),
            {'time_offset': 2},
            format='json',
        )
        self.assertEqual(regenerate_response.status_code, status.HTTP_200_OK)
        self.assertTrue(regenerate_response.data['thumbnail'])
        self.assertNotEqual(regenerate_response.data['thumbnail'], original_thumbnail)

    def test_non_owner_cannot_patch_or_regenerate_thumbnail(self):
        owner = self.authenticate()
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Owner video',
                'file': SimpleUploadedFile('owner.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        video_id = upload_response.data['id']

        other_user = self.create_user(email='other-owner@example.com')
        self.client.force_authenticate(user=other_user)

        patch_response = self.client.patch(
            reverse('video-detail', args=[video_id]),
            {'title': 'Hacked'},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_404_NOT_FOUND)

        regenerate_response = self.client.post(
            reverse('video-regenerate-thumbnail', args=[video_id]),
            {'time_offset': 0.5},
            format='json',
        )
        self.assertEqual(regenerate_response.status_code, status.HTTP_404_NOT_FOUND)

        self.assertEqual(owner.videos.count(), 1)

    def test_public_categories_include_seeded_metadata_and_empty_categories(self):
        self.authenticate()
        self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Tech video',
                'category': 'technology',
                'file': SimpleUploadedFile('tech.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse('public-category-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        category_payload = {item['slug']: item for item in response.data}
        self.assertIn('technology', category_payload)
        self.assertNotIn('tech', category_payload)
        self.assertEqual(category_payload['technology']['name'], 'Technology')
        self.assertEqual(category_payload['technology']['sort_order'], 1)
        self.assertTrue(category_payload['technology']['show_on_homepage'])
        self.assertEqual(
            category_payload['technology']['description'],
            'Tech demos, software, infrastructure, AI, and engineering content.',
        )
        self.assertIn('entertainment', category_payload)
        self.assertEqual(category_payload['entertainment']['sort_order'], 5)
        self.assertTrue(category_payload['entertainment']['show_on_homepage'])
        self.assertEqual(
            category_payload['entertainment']['description'],
            'General entertainment, shows, fun content, lifestyle, and casual viewing.',
        )
        self.assertFalse(category_payload['other']['show_on_homepage'])

    def test_inactive_category_is_hidden_and_rejected_for_video_write(self):
        self.authenticate()
        category = Category.objects.create(name='Secret', slug='secret', is_active=False)

        list_response = self.client.get(reverse('public-category-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertNotIn(category.slug, [item['slug'] for item in list_response.data])

        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Secret upload',
                'category': 'secret',
                'file': SimpleUploadedFile('secret.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.assertEqual(upload_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('category', upload_response.data)


    def test_video_like_delete_and_public_view_tracking(self):
        owner = self.authenticate()
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Engagement video',
                'category': 'technology',
                'file': SimpleUploadedFile('engagement.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        video_id = upload_response.data['id']
        self.assertEqual(upload_response.data['like_count'], 0)
        self.assertEqual(upload_response.data['view_count'], 0)
        self.assertFalse(upload_response.data['is_liked'])

        like_response = self.client.post(reverse('video-like', args=[video_id]))
        self.assertEqual(like_response.status_code, status.HTTP_200_OK)
        self.assertEqual(like_response.data['like_count'], 1)
        self.assertTrue(like_response.data['viewer_has_liked'])

        duplicate_like_response = self.client.post(reverse('video-like', args=[video_id]))
        self.assertEqual(duplicate_like_response.status_code, status.HTTP_200_OK)
        self.assertEqual(duplicate_like_response.data['like_count'], 1)

        self.client.force_authenticate(user=None)
        public_view_response = self.client.post(reverse('public-video-view', args=[video_id]))
        self.assertEqual(public_view_response.status_code, status.HTTP_200_OK)
        self.assertEqual(public_view_response.data['view_count'], 1)
        self.assertEqual(public_view_response.data['like_count'], 1)
        self.assertFalse(public_view_response.data['is_liked'])

        self.client.force_authenticate(user=owner)
        detail_response = self.client.get(reverse('video-detail', args=[video_id]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['view_count'], 1)
        self.assertEqual(detail_response.data['like_count'], 1)
        self.assertTrue(detail_response.data['is_liked'])

        unlike_response = self.client.delete(reverse('video-like', args=[video_id]))
        self.assertEqual(unlike_response.status_code, status.HTTP_200_OK)
        self.assertEqual(unlike_response.data['like_count'], 0)
        self.assertFalse(unlike_response.data['viewer_has_liked'])


    def test_public_interaction_summary_comments_and_channel_subscription(self):
        channel_owner = self.authenticate(email='channel@example.com')
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Commentable video',
                'category': 'education',
                'file': SimpleUploadedFile('commentable.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        video_id = upload_response.data['id']

        subscriber = self.create_user(email='subscriber@example.com', first_name='Sub', last_name='User')
        self.client.force_authenticate(user=subscriber)

        subscribe_response = self.client.post(reverse('channel-subscribe', args=[channel_owner.id]))
        self.assertEqual(subscribe_response.status_code, status.HTTP_200_OK)
        self.assertTrue(subscribe_response.data['viewer_is_subscribed'])
        self.assertEqual(subscribe_response.data['subscriber_count'], 1)

        comment_response = self.client.post(
            reverse('video-comment-create', args=[video_id]),
            {'content': 'Great upload!'},
            format='json',
        )
        self.assertEqual(comment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(comment_response.data['content'], 'Great upload!')
        self.assertEqual(comment_response.data['video_id'], video_id)
        self.assertIsNone(comment_response.data['parent_id'])
        self.assertEqual(comment_response.data['user']['name'], 'Sub User')
        self.assertEqual(comment_response.data['like_count'], 0)
        self.assertEqual(comment_response.data['reply_count'], 0)

        summary_response = self.client.get(reverse('public-video-interaction-summary', args=[video_id]))
        self.assertEqual(summary_response.status_code, status.HTTP_200_OK)
        self.assertEqual(summary_response.data['video_id'], video_id)
        self.assertEqual(summary_response.data['like_count'], 0)
        self.assertEqual(summary_response.data['comment_count'], 1)
        self.assertFalse(summary_response.data['viewer_has_liked'])
        self.assertTrue(summary_response.data['viewer_is_subscribed'])
        self.assertEqual(summary_response.data['channel_id'], channel_owner.id)
        self.assertEqual(summary_response.data['subscriber_count'], 1)

        public_comments_response = self.client.get(reverse('public-video-comments', args=[video_id]))
        self.assertEqual(public_comments_response.status_code, status.HTTP_200_OK)
        self.assertEqual(public_comments_response.data['count'], 1)
        self.assertEqual(len(public_comments_response.data['results']), 1)
        self.assertEqual(public_comments_response.data['results'][0]['content'], 'Great upload!')

        unsubscribe_response = self.client.delete(reverse('channel-subscribe', args=[channel_owner.id]))
        self.assertEqual(unsubscribe_response.status_code, status.HTTP_200_OK)
        self.assertFalse(unsubscribe_response.data['viewer_is_subscribed'])
        self.assertEqual(unsubscribe_response.data['subscriber_count'], 0)



    def test_comment_create_explicitly_accepts_json_and_rejects_text_plain(self):
        self.authenticate()
        video_id = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Parser video',
                'file': SimpleUploadedFile('parser.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data['id']

        json_response = self.client.post(
            reverse('video-comment-create', args=[video_id]),
            {'content': 'JSON comment body'},
            format='json',
        )
        self.assertEqual(json_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(json_response.data['content'], 'JSON comment body')

        text_plain_response = self.client.generic(
            'POST',
            reverse('video-comment-create', args=[video_id]),
            'raw text body',
            content_type='text/plain',
        )
        self.assertEqual(text_plain_response.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    def test_comment_create_requires_auth_and_increments_comment_count(self):
        self.authenticate()
        upload_response = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Comments video',
                'file': SimpleUploadedFile('comments.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        video_id = upload_response.data['id']
        self.client.force_authenticate(user=None)

        unauthenticated_response = self.client.post(
            reverse('video-comment-create', args=[video_id]),
            {'content': 'Blocked'},
            format='json',
        )
        self.assertEqual(unauthenticated_response.status_code, status.HTTP_401_UNAUTHORIZED)

        commenter = self.create_user(email='commenter@example.com', first_name='Comment', last_name='User')
        self.client.force_authenticate(user=commenter)
        create_response = self.client.post(
            reverse('video-comment-create', args=[video_id]),
            {'content': '  Real comment body  '},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data['content'], 'Real comment body')

        summary_response = self.client.get(reverse('public-video-interaction-summary', args=[video_id]))
        self.assertEqual(summary_response.status_code, status.HTTP_200_OK)
        self.assertEqual(summary_response.data['comment_count'], 1)

    def test_comment_parent_must_belong_to_same_video(self):
        self.authenticate()
        first_video_id = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'First video',
                'file': SimpleUploadedFile('first-parent.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data['id']
        second_video_id = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Second video',
                'file': SimpleUploadedFile('second-parent.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data['id']

        parent_response = self.client.post(
            reverse('video-comment-create', args=[first_video_id]),
            {'content': 'Parent comment'},
            format='json',
        )
        self.assertEqual(parent_response.status_code, status.HTTP_201_CREATED)

        invalid_reply_response = self.client.post(
            reverse('video-comment-create', args=[second_video_id]),
            {'content': 'Reply on wrong video', 'parent_id': parent_response.data['id']},
            format='json',
        )
        self.assertEqual(invalid_reply_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent_id', invalid_reply_response.data)

    def test_deleted_comments_are_hidden_from_public_list(self):
        self.authenticate()
        video_id = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Hide deleted comments',
                'file': SimpleUploadedFile('deleted-comments.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data['id']
        visible_comment = self.client.post(
            reverse('video-comment-create', args=[video_id]),
            {'content': 'Visible comment'},
            format='json',
        ).data
        hidden_comment = self.client.post(
            reverse('video-comment-create', args=[video_id]),
            {'content': 'Hidden comment'},
            format='json',
        ).data

        from apps.accounts.models import VideoComment
        VideoComment.objects.filter(pk=hidden_comment['id']).update(is_deleted=True)

        self.client.force_authenticate(user=None)
        response = self.client.get(reverse('public-video-comments', args=[video_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], visible_comment['id'])

    def test_public_related_videos_prefers_same_category_and_excludes_current(self):
        owner = self.authenticate()
        current_video = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Current tech video',
                'category': 'technology',
                'file': SimpleUploadedFile('current.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data
        self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Related tech video',
                'category': 'technology',
                'description': 'A' * 160,
                'file': SimpleUploadedFile('related.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Education video',
                'category': 'education',
                'file': SimpleUploadedFile('education.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse('public-video-related', args=[current_video['id']]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['title'], 'Related tech video')
        self.assertEqual(response.data[0]['category_slug'], 'technology')
        self.assertTrue(response.data[0]['description_preview'].endswith('...'))

        self.assertEqual(owner.videos.count(), 3)

class LiveStreamAPITestCase(APITestCase):
    def create_user(self, email, password='strong-pass-123', **extra_fields):
        return User.objects.create_user(email=email, password=password, **extra_fields)

    def authenticate(self, email='streamer@example.com'):
        user = self.create_user(email=email)
        self.client.force_authenticate(user=user)
        return user

    def test_live_stream_endpoints_require_authentication(self):
        list_response = self.client.get(reverse('live-stream-list'))
        self.assertEqual(list_response.status_code, status.HTTP_401_UNAUTHORIZED)

        create_response = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Unauth stream'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_owner_can_create_start_end_and_list_live_streams(self):
        self.authenticate()
        create_response = self.client.post(
            reverse('live-stream-create'),
            {'title': 'My live stream', 'category': 'technology'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        stream_id = create_response.data['id']
        self.assertEqual(create_response.data['status'], 'idle')
        self.assertTrue(create_response.data['stream_key'])
        self.assertIsNone(create_response.data['rtmp_url'])
        self.assertIsNone(create_response.data['playback_url'])

        detail_response = self.client.get(reverse('live-stream-detail', args=[stream_id]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['title'], 'My live stream')

        start_response = self.client.post(reverse('live-stream-start', args=[stream_id]), format='json')
        self.assertEqual(start_response.status_code, status.HTTP_200_OK)
        self.assertEqual(start_response.data['status'], 'live')
        self.assertIsNotNone(start_response.data['started_at'])

        end_response = self.client.post(reverse('live-stream-end', args=[stream_id]), format='json')
        self.assertEqual(end_response.status_code, status.HTTP_200_OK)
        self.assertEqual(end_response.data['status'], 'ended')
        self.assertIsNotNone(end_response.data['ended_at'])

        list_response = self.client.get(reverse('live-stream-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]['id'], stream_id)

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_APPLICATION='LiveApp',
        ANT_MEDIA_RTMP_BASE='rtmp://ant.example.com/LiveApp',
        ANT_MEDIA_PLAYBACK_BASE='https://ant.example.com/LiveApp/streams',
    )
    def test_live_stream_returns_ant_media_connection_urls(self):
        self.authenticate()
        create_response = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Playback stream'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(create_response.data['rtmp_url'].startswith('rtmp://ant.example.com/LiveApp/'))
        self.assertIn('/LiveApp/streams/', create_response.data['playback_url'])
        self.assertTrue(create_response.data['playback_url'].endswith('.m3u8'))

    def test_non_owner_cannot_start_or_end_stream(self):
        owner = self.authenticate()
        stream_id = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Owner stream'},
            format='json',
        ).data['id']

        other_user = self.create_user('other-streamer@example.com')
        self.client.force_authenticate(user=other_user)

        start_response = self.client.post(reverse('live-stream-start', args=[stream_id]), format='json')
        self.assertEqual(start_response.status_code, status.HTTP_404_NOT_FOUND)

        end_response = self.client.post(reverse('live-stream-end', args=[stream_id]), format='json')
        self.assertEqual(end_response.status_code, status.HTTP_404_NOT_FOUND)
