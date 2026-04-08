import shutil
import tempfile
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.content import (
    UnifiedContentSerializer,
    map_live_to_content,
    map_video_to_content,
)
from apps.accounts.models import (
    Category,
    LiveChatMessage,
    LiveChatRoom,
    LiveStream,
    LiveStreamProduct,
    PaymentOrder,
    Product,
    SellerStore,
    StreamPaymentMethod,
    Video,
)
from apps.accounts.serializers import LiveStreamSerializer

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

    def test_auth_contract_response_shapes(self):
        register_response = self.client.post(
            reverse('auth-register'),
            {
                'email': 'contract-auth@example.com',
                'password': 'strong-pass-123',
                'first_name': 'Contract',
                'last_name': 'User',
            },
            format='json',
        )
        self.assertEqual(register_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            set(register_response.data.keys()),
            {'id', 'email', 'first_name', 'last_name'},
        )

        login_response = self.client.post(
            reverse('auth-login'),
            {
                'email': 'contract-auth@example.com',
                'password': 'strong-pass-123',
            },
            format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', login_response.data)
        self.assertIn('refresh', login_response.data)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login_response.data['access']}")
        me_response = self.client.get(reverse('auth-me'))
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(me_response.data.keys()), {'id', 'email', 'first_name', 'last_name', 'is_creator'})

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


class AccountMenuAPITestCase(APITestCase):
    def create_user(self, email, password='strong-pass-123', **extra_fields):
        defaults = {
            'first_name': 'Menu',
            'last_name': 'User',
        }
        defaults.update(extra_fields)
        return User.objects.create_user(email=email, password=password, **defaults)

    def test_profile_endpoints_require_authentication(self):
        response = self.client.get(reverse('account-profile'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        patch_response = self.client.patch(
            reverse('account-profile'),
            {'bio': 'No auth'},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_401_UNAUTHORIZED)

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_profile_get_and_patch(self):
        user = self.create_user('account@example.com')
        self.client.force_authenticate(user=user)

        get_response = self.client.get(reverse('account-profile'))
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.data['id'], user.id)
        self.assertEqual(get_response.data['email'], user.email)
        self.assertFalse(get_response.data['is_creator'])
        self.assertFalse(get_response.data['is_seller'])
        self.assertFalse(get_response.data['is_admin'])
        self.assertFalse(get_response.data['can_create_live'])
        self.assertFalse(get_response.data['can_manage_store'])
        self.assertFalse(get_response.data['can_accept_payments'])
        self.assertIsNone(get_response.data['seller_store'])
        self.assertEqual(
            get_response.data['counts'],
            {'videos': 0, 'live_streams': 0, 'products': 0, 'payment_methods': 0, 'orders': 0},
        )
        self.assertEqual(get_response.data['display_name'], 'Menu User')
        self.assertIsNone(get_response.data['avatar_url'])

        patch_response = self.client.patch(
            reverse('account-profile'),
            {
                'first_name': 'Updated',
                'last_name': 'Name',
                'bio': 'About me',
                'avatar': SimpleUploadedFile('avatar.png', b'avatar-bytes', content_type='image/png'),
            },
            format='multipart',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['display_name'], 'Updated Name')
        self.assertEqual(patch_response.data['bio'], 'About me')
        self.assertIn('/media/avatars/', patch_response.data['avatar_url'])
        self.assertEqual(patch_response.data['id'], user.id)
        self.assertEqual(patch_response.data['email'], user.email)

    def test_profile_creator_without_store_shows_capabilities(self):
        user = self.create_user('creator@example.com', is_creator=True)
        self.client.force_authenticate(user=user)

        LiveStream.objects.create(owner=user, title='Creator live')
        response = self.client.get(reverse('account-profile'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_creator'])
        self.assertFalse(response.data['is_seller'])
        self.assertFalse(response.data['can_manage_store'])
        self.assertTrue(response.data['can_create_live'])
        self.assertTrue(response.data['can_accept_payments'])
        self.assertEqual(response.data['counts']['live_streams'], 1)
        self.assertEqual(response.data['counts']['products'], 0)

    def test_profile_seller_with_active_store_summary_and_counts(self):
        user = self.create_user('seller@example.com')
        self.client.force_authenticate(user=user)
        store = SellerStore.objects.create(owner=user, name='Seller Store', slug='seller-store', is_active=True)
        product = Product.objects.create(
            store=store,
            title='Seller Product',
            slug='seller-product',
            price_amount='11.00',
            price_currency='USD',
            stock_quantity=5,
            status=Product.STATUS_ACTIVE,
        )
        stream = LiveStream.objects.create(owner=user, title='Seller live')
        StreamPaymentMethod.objects.create(
            stream=stream,
            method_type=StreamPaymentMethod.TYPE_PAY_QR,
            title='Seller PM',
            is_active=True,
        )
        PaymentOrder.objects.create(
            user=user,
            stream=stream,
            product=product,
            order_type=PaymentOrder.TYPE_PRODUCT,
            amount='11.00',
            currency='USD',
        )
        Video.objects.create(
            owner=user,
            title='Seller video',
            file=SimpleUploadedFile('seller.mp4', b'video-bytes', content_type='video/mp4'),
        )

        response = self.client.get(reverse('account-profile'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_seller'])
        self.assertTrue(response.data['can_manage_store'])
        self.assertTrue(response.data['can_accept_payments'])
        self.assertEqual(
            response.data['seller_store'],
            {
                'id': store.id,
                'name': 'Seller Store',
                'slug': 'seller-store',
                'is_active': True,
            },
        )
        self.assertEqual(response.data['counts']['videos'], 1)
        self.assertEqual(response.data['counts']['live_streams'], 1)
        self.assertEqual(response.data['counts']['products'], 1)
        self.assertEqual(response.data['counts']['payment_methods'], 1)
        self.assertEqual(response.data['counts']['orders'], 1)

    def test_profile_staff_user_has_admin_flag(self):
        user = self.create_user('staff@example.com', is_staff=True)
        self.client.force_authenticate(user=user)
        response = self.client.get(reverse('account-profile'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['is_admin'])

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_profile_patch_supports_display_name_and_avatar_clear(self):
        user = self.create_user('display-name@example.com', first_name='Old', last_name='Name')
        self.client.force_authenticate(user=user)

        response = self.client.patch(
            reverse('account-profile'),
            {
                'display_name': 'New Display',
                'bio': '',
                'avatar': SimpleUploadedFile('avatar.png', b'avatar-bytes', content_type='image/png'),
            },
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['display_name'], 'New Display')
        self.assertEqual(response.data['first_name'], 'New')
        self.assertEqual(response.data['last_name'], 'Display')
        self.assertEqual(response.data['bio'], '')
        self.assertIsNotNone(response.data['avatar_url'])

        clear_response = self.client.patch(
            reverse('account-profile'),
            {'avatar_clear': True},
            format='json',
        )
        self.assertEqual(clear_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(clear_response.data['avatar_url'])

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_profile_avatar_contract_prefers_avatar_url_and_reflects_get_after_updates(self):
        user = self.create_user('avatar-contract@example.com')
        self.client.force_authenticate(user=user)

        initial_get = self.client.get(reverse('account-profile'))
        self.assertEqual(initial_get.status_code, status.HTTP_200_OK)
        self.assertIsNone(initial_get.data['avatar'])
        self.assertIsNone(initial_get.data['avatar_url'])

        upload_response = self.client.patch(
            reverse('account-profile'),
            {'avatar': SimpleUploadedFile('avatar.png', b'avatar-bytes', content_type='image/png')},
            format='multipart',
        )
        self.assertEqual(upload_response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(upload_response.data['avatar'])
        self.assertIsNotNone(upload_response.data['avatar_url'])
        self.assertTrue(upload_response.data['avatar_url'].startswith('http://testserver/media/avatars/'))

        get_after_upload = self.client.get(reverse('account-profile'))
        self.assertEqual(get_after_upload.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(get_after_upload.data['avatar'])
        self.assertTrue(get_after_upload.data['avatar_url'].startswith('http://testserver/media/avatars/'))

        clear_response = self.client.patch(
            reverse('account-profile'),
            {'avatar_clear': True},
            format='json',
        )
        self.assertEqual(clear_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(clear_response.data['avatar_url'])

        get_after_clear = self.client.get(reverse('account-profile'))
        self.assertEqual(get_after_clear.status_code, status.HTTP_200_OK)
        self.assertIsNone(get_after_clear.data['avatar'])
        self.assertIsNone(get_after_clear.data['avatar_url'])

    def test_profile_patch_keeps_email_read_only(self):
        user = self.create_user('email-readonly@example.com')
        self.client.force_authenticate(user=user)
        response = self.client.patch(
            reverse('account-profile'),
            {'email': 'new-email@example.com', 'bio': 'new bio'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['email'], 'email-readonly@example.com')
        user.refresh_from_db()
        self.assertEqual(user.email, 'email-readonly@example.com')

    def test_change_password_success(self):
        user = self.create_user('change-password@example.com')
        self.client.force_authenticate(user=user)

        response = self.client.post(
            reverse('account-change-password'),
            {'current_password': 'strong-pass-123', 'new_password': 'new-Strong-pass-456'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], 'Password updated successfully.')
        user.refresh_from_db()
        self.assertTrue(user.check_password('new-Strong-pass-456'))

    def test_change_password_rejects_wrong_current_password(self):
        user = self.create_user('change-password-wrong@example.com')
        self.client.force_authenticate(user=user)

        response = self.client.post(
            reverse('account-change-password'),
            {'current_password': 'wrong-password', 'new_password': 'new-Strong-pass-456'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('current_password', response.data)

    def test_change_password_rejects_weak_password(self):
        user = self.create_user('change-password-weak@example.com')
        self.client.force_authenticate(user=user)

        response = self.client.post(
            reverse('account-change-password'),
            {'current_password': 'strong-pass-123', 'new_password': '123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('new_password', response.data)

    def test_preferences_get_and_patch(self):
        user = self.create_user('prefs@example.com')
        self.client.force_authenticate(user=user)

        get_response = self.client.get(reverse('account-preferences'))
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.data['language'], 'en-US')
        self.assertEqual(get_response.data['theme'], 'system')
        self.assertEqual(get_response.data['timezone'], '')

        patch_response = self.client.patch(
            reverse('account-preferences'),
            {'language': 'th-TH', 'theme': 'dark', 'timezone': 'Asia/Bangkok'},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['language'], 'th-TH')
        self.assertEqual(patch_response.data['theme'], 'dark')
        self.assertEqual(patch_response.data['timezone'], 'Asia/Bangkok')

    def test_preferences_reject_invalid_values(self):
        user = self.create_user('prefs-invalid@example.com')
        self.client.force_authenticate(user=user)

        invalid_response = self.client.patch(
            reverse('account-preferences'),
            {'language': 'xx-YY', 'theme': 'neon'},
            format='json',
        )
        self.assertEqual(invalid_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('language', invalid_response.data)
        self.assertIn('theme', invalid_response.data)


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
                'visibility': 'private',
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
        self.assertEqual(upload_response.data['visibility'], 'private')
        self.assertEqual(upload_response.data['category'], 'technology')
        self.assertTrue(upload_response.data['thumbnail'])
        self.assertIn('/media/thumbnails/', upload_response.data['thumbnail_url'])

        created_video = user.videos.get(pk=video_id)
        self.assertEqual(created_video.description, 'My video description')
        self.assertEqual(created_video.visibility, Video.VISIBILITY_PRIVATE)
        self.assertIsNotNone(created_video.category)
        self.assertEqual(created_video.category.slug, 'technology')

        list_response = self.client.get(reverse('video-list-create'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data['count'], 1)
        self.assertEqual(len(list_response.data['results']), 1)
        self.assertEqual(list_response.data['results'][0]['title'], 'My first video')
        self.assertEqual(list_response.data['results'][0]['visibility'], 'private')
        self.assertIn('/media/thumbnails/', list_response.data['results'][0]['thumbnail_url'])

        detail_response = self.client.get(reverse('video-detail', args=[video_id]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['title'], 'My first video')
        self.assertEqual(detail_response.data['category_name'], 'Technology')
        self.assertEqual(detail_response.data['category_slug'], 'technology')
        self.assertEqual(detail_response.data['description_preview'], 'My video description')
        self.assertEqual(detail_response.data['visibility'], 'private')
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

    def test_owner_can_update_video_visibility(self):
        self.authenticate()
        video_id = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Visibility update video',
                'visibility': 'public',
                'file': SimpleUploadedFile('vis-update.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data['id']

        patch_response = self.client.patch(
            reverse('video-detail', args=[video_id]),
            {'visibility': 'private'},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['visibility'], 'private')
        self.assertEqual(Video.objects.get(pk=video_id).visibility, Video.VISIBILITY_PRIVATE)

    def test_owner_list_includes_private_videos(self):
        self.authenticate()
        self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Public dashboard item',
                'visibility': 'public',
                'file': SimpleUploadedFile('owner-public.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Private dashboard item',
                'visibility': 'private',
                'file': SimpleUploadedFile('owner-private.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        )
        list_response = self.client.get(reverse('video-list-create'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        titles = {item['title'] for item in list_response.data['results']}
        self.assertIn('Public dashboard item', titles)
        self.assertIn('Private dashboard item', titles)

    def test_owner_video_contract_fields_for_list_and_detail(self):
        user = self.authenticate()
        video = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Owner contract video',
                'description': 'Owner contract description',
                'category': 'technology',
                'file': SimpleUploadedFile('owner-contract.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data

        list_response = self.client.get(reverse('video-list-create'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        expected_keys = {
            'id', 'owner_id', 'owner_name', 'owner_avatar_url', 'title', 'description',
            'description_preview', 'visibility', 'category', 'category_name', 'category_slug', 'like_count',
            'comment_count', 'view_count', 'is_liked', 'file', 'file_url', 'thumbnail',
            'thumbnail_url', 'created_at',
        }
        self.assertTrue(expected_keys.issubset(set(list_response.data['results'][0].keys())))
        self.assertEqual(list_response.data['results'][0]['owner_id'], user.id)

        detail_response = self.client.get(reverse('video-detail', args=[video['id']]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertTrue(expected_keys.issubset(set(detail_response.data.keys())))


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

    def test_public_video_endpoints_only_expose_public_visibility(self):
        self.authenticate()
        public_video = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Public item',
                'visibility': 'public',
                'file': SimpleUploadedFile('public-item.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data
        private_video = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Private item',
                'visibility': 'private',
                'file': SimpleUploadedFile('private-item.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data
        self.client.force_authenticate(user=None)

        list_response = self.client.get(reverse('public-video-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        listed_ids = [item['id'] for item in list_response.data['results']]
        self.assertIn(public_video['id'], listed_ids)
        self.assertNotIn(private_video['id'], listed_ids)

        public_detail_response = self.client.get(reverse('public-video-detail', args=[public_video['id']]))
        self.assertEqual(public_detail_response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            self.client.get(reverse('public-video-detail', args=[private_video['id']])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(reverse('public-video-interaction-summary', args=[private_video['id']])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(reverse('public-video-comments', args=[private_video['id']])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.post(reverse('public-video-view', args=[private_video['id']])).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.get(reverse('public-video-related', args=[private_video['id']])).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_public_video_contract_fields_are_stable_for_frontend(self):
        self.authenticate()
        video = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Contract video',
                'description': 'Contract body',
                'category': 'technology',
                'file': SimpleUploadedFile('contract.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data
        self.client.force_authenticate(user=None)

        detail_response = self.client.get(reverse('public-video-detail', args=[video['id']]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        expected_keys = {
            'id', 'owner_id', 'owner_name', 'owner_avatar_url', 'title', 'description',
            'description_preview', 'visibility', 'category', 'category_name', 'category_slug', 'like_count',
            'comment_count', 'view_count', 'is_liked', 'file', 'file_url', 'thumbnail',
            'thumbnail_url', 'created_at',
        }
        self.assertTrue(expected_keys.issubset(set(detail_response.data.keys())))
        self.assertEqual(detail_response.data['category'], 'technology')
        self.assertFalse(detail_response.data['is_liked'])

        list_response = self.client.get(reverse('public-video-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertIn('count', list_response.data)
        self.assertIn('results', list_response.data)
        self.assertTrue(expected_keys.issubset(set(list_response.data['results'][0].keys())))

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

    def test_interaction_summary_contract_fields(self):
        self.authenticate()
        video_id = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Summary contract video',
                'file': SimpleUploadedFile('summary-contract.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data['id']
        self.client.force_authenticate(user=None)

        response = self.client.get(reverse('public-video-interaction-summary', args=[video_id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data.keys()),
            {'video_id', 'like_count', 'comment_count', 'viewer_has_liked', 'viewer_is_subscribed', 'channel_id', 'subscriber_count'},
        )

    def test_public_comments_contract_fields(self):
        self.authenticate()
        video_id = self.client.post(
            reverse('video-list-create'),
            {
                'title': 'Comment contract video',
                'file': SimpleUploadedFile('comment-contract.mp4', b'video-bytes', content_type='video/mp4'),
            },
            format='multipart',
        ).data['id']
        create_comment_response = self.client.post(
            reverse('video-comment-create', args=[video_id]),
            {'content': 'Comment contract body'},
            format='json',
        )
        self.assertEqual(create_comment_response.status_code, status.HTTP_201_CREATED)
        self.client.force_authenticate(user=None)

        list_response = self.client.get(reverse('public-video-comments', args=[video_id]))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertIn('count', list_response.data)
        self.assertIn('results', list_response.data)
        comment_payload = list_response.data['results'][0]
        self.assertEqual(
            set(comment_payload.keys()),
            {'id', 'video_id', 'parent_id', 'content', 'created_at', 'updated_at', 'like_count', 'reply_count', 'viewer_has_liked', 'user'},
        )
        self.assertEqual(set(comment_payload['user'].keys()), {'id', 'name', 'avatar_url'})



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
        user = self.create_user(email=email, is_creator=True)
        self.client.force_authenticate(user=user)
        return user

    def test_live_stream_endpoints_require_authentication(self):
        list_response = self.client.get(reverse('live-stream-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data, [])

        create_response = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Unauth stream'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_creator_cannot_create_live_stream(self):
        non_creator = self.create_user('viewer@example.com', is_creator=False)
        self.client.force_authenticate(user=non_creator)
        response = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Blocked stream'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_non_creator_cannot_prepare_start_or_end_even_as_owner(self):
        owner = self.create_user('noncreator-owner@example.com', is_creator=False)
        stream = LiveStream.objects.create(owner=owner, title='Owner stream')
        self.client.force_authenticate(user=owner)
        self.assertEqual(
            self.client.post(reverse('live-stream-prepare', args=[stream.id]), format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(reverse('live-stream-start', args=[stream.id]), format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.post(reverse('live-stream-end', args=[stream.id]), format='json').status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_owner_can_create_start_end_and_list_live_streams(self):
        user = self.authenticate()
        create_response = self.client.post(
            reverse('live-stream-create'),
            {
                'title': 'My live stream',
                'description': 'Camera and encoder ready',
                'payment_address': '0xabc123',
                'category': 'technology',
                'visibility': 'unlisted',
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        stream_id = create_response.data['id']
        self.assertEqual(create_response.data['owner_id'], user.id)
        self.assertEqual(create_response.data['owner_name'], user.email)
        self.assertEqual(create_response.data['description'], 'Camera and encoder ready')
        self.assertEqual(create_response.data['payment_address'], '0xabc123')
        self.assertEqual(create_response.data['category_name'], 'Technology')
        self.assertEqual(create_response.data['visibility'], 'unlisted')
        self.assertEqual(create_response.data['status'], 'ready')
        self.assertEqual(create_response.data['status_source'], 'django_control')
        self.assertNotIn('stream_key', create_response.data)
        self.assertEqual(create_response.data['rtmp_url'], 'rtmp://media.meownews.online/live')
        self.assertTrue(create_response.data['watch_url'].endswith(f'/live/{stream_id}'))
        self.assertTrue(
            create_response.data['playback_url'].startswith('https://media.meownews.online/live/streams/')
        )
        self.assertNotEqual(create_response.data['watch_url'], create_response.data['playback_url'])
        self.assertIsNone(create_response.data['thumbnail_url'])
        self.assertIsNone(create_response.data['preview_image_url'])
        self.assertIsNone(create_response.data['snapshot_url'])

        detail_response = self.client.get(reverse('live-stream-detail', args=[stream_id]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['title'], 'My live stream')
        self.assertEqual(detail_response.data['description'], 'Camera and encoder ready')
        self.assertEqual(detail_response.data['payment_address'], '0xabc123')
        self.assertEqual(detail_response.data['visibility'], 'unlisted')
        self.assertEqual(detail_response.data['owner_id'], user.id)
        self.assertEqual(detail_response.data['category_name'], 'Technology')
        self.assertEqual(detail_response.data['status_source'], 'django_control')
        self.assertEqual(detail_response.data['status'], 'ready')
        self.assertEqual(detail_response.data['stream_key'], LiveStream.objects.get(pk=stream_id).stream_key)
        self.assertTrue(detail_response.data['watch_url'].endswith(f'/live/{stream_id}'))
        self.assertNotEqual(detail_response.data['watch_url'], detail_response.data['playback_url'])

        start_response = self.client.post(reverse('live-stream-start', args=[stream_id]), format='json')
        self.assertEqual(start_response.status_code, status.HTTP_200_OK)
        self.assertEqual(start_response.data['status'], 'live')
        self.assertEqual(start_response.data['django_status'], 'live')
        self.assertEqual(start_response.data['effective_status'], 'live')
        self.assertEqual(start_response.data['status_source'], 'django_control')
        self.assertIsNone(start_response.data['raw_ant_media_status'])
        self.assertFalse(start_response.data['can_start'])
        self.assertTrue(start_response.data['can_end'])
        self.assertFalse(start_response.data['sync_ok'])
        self.assertEqual(start_response.data['sync_error'], 'sync_disabled')
        self.assertTrue(start_response.data['watch_url'].endswith(f'/live/{stream_id}'))
        self.assertNotEqual(start_response.data['watch_url'], start_response.data['playback_url'])
        self.assertIsNotNone(start_response.data['started_at'])

        end_response = self.client.post(reverse('live-stream-end', args=[stream_id]), format='json')
        self.assertEqual(end_response.status_code, status.HTTP_200_OK)
        self.assertEqual(end_response.data['status'], 'ended')
        self.assertEqual(end_response.data['django_status'], 'ended')
        self.assertEqual(end_response.data['effective_status'], 'ended')
        self.assertFalse(end_response.data['can_end'])
        self.assertTrue(end_response.data['can_start'])
        self.assertFalse(end_response.data['sync_ok'])
        self.assertTrue(end_response.data['watch_url'].endswith(f'/live/{stream_id}'))
        self.assertNotEqual(end_response.data['watch_url'], end_response.data['playback_url'])
        self.assertIsNotNone(end_response.data['ended_at'])

        list_response = self.client.get(reverse('live-stream-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]['id'], stream_id)

    def test_live_stream_contract_fields_on_create_and_detail(self):
        self.authenticate()
        create_response = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Live contract stream', 'visibility': 'public'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        expected_keys = {
            'id', 'owner_id', 'owner_name', 'title', 'description', 'payment_address',
            'category', 'visibility', 'status', 'django_status', 'effective_status', 'status_source',
            'raw_ant_media_status',
            'rtmp_url', 'playback_url', 'watch_url', 'thumbnail_url', 'preview_image_url', 'snapshot_url',
            'viewer_count', 'can_start', 'can_end', 'sync_ok', 'sync_error', 'message',
            'started_at', 'ended_at', 'created_at',
        }
        self.assertTrue(expected_keys.issubset(set(create_response.data.keys())))

        detail_response = self.client.get(reverse('live-stream-detail', args=[create_response.data['id']]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertTrue(expected_keys.issubset(set(detail_response.data.keys())))

    def test_public_can_list_and_retrieve_public_live_stream_metadata(self):
        owner = self.create_user('public-streamer@example.com')
        public_stream = LiveStream.objects.create(
            owner=owner,
            title='Public stream',
            description='Browser studio compatible',
            payment_address='0xfeedbeef',
            visibility=LiveStream.VISIBILITY_PUBLIC,
        )
        LiveStream.objects.create(
            owner=owner,
            title='Private stream',
            description='Hidden studio',
            visibility=LiveStream.VISIBILITY_PRIVATE,
        )

        list_response = self.client.get(reverse('live-stream-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]['id'], public_stream.id)
        self.assertEqual(list_response.data[0]['owner_id'], owner.id)
        self.assertEqual(list_response.data[0]['owner_name'], owner.email)
        self.assertEqual(list_response.data[0]['visibility'], LiveStream.VISIBILITY_PUBLIC)
        self.assertEqual(list_response.data[0]['status'], 'ready')
        self.assertEqual(list_response.data[0]['status_source'], 'django_control')
        self.assertIsNone(list_response.data[0]['thumbnail_url'])
        self.assertIsNone(list_response.data[0]['preview_image_url'])
        self.assertIsNone(list_response.data[0]['snapshot_url'])
        self.assertNotIn('stream_key', list_response.data[0])

        detail_response = self.client.get(reverse('live-stream-detail', args=[public_stream.id]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['description'], 'Browser studio compatible')
        self.assertEqual(detail_response.data['payment_address'], '0xfeedbeef')
        self.assertEqual(detail_response.data['owner_id'], owner.id)
        self.assertEqual(detail_response.data['stream_key'], public_stream.stream_key)

    def test_public_cannot_retrieve_private_live_stream(self):
        owner = self.create_user('private-streamer@example.com')
        private_stream = LiveStream.objects.create(
            owner=owner,
            title='Private stream',
            visibility=LiveStream.VISIBILITY_PRIVATE,
        )

        response = self.client.get(reverse('live-stream-detail', args=[private_stream.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_live_stream_status_endpoint_visibility_rules(self):
        owner = self.create_user('status-owner@example.com')
        public_stream = LiveStream.objects.create(
            owner=owner,
            title='Public status stream',
            visibility=LiveStream.VISIBILITY_PUBLIC,
        )
        private_stream = LiveStream.objects.create(
            owner=owner,
            title='Private status stream',
            visibility=LiveStream.VISIBILITY_PRIVATE,
        )

        public_response = self.client.get(reverse('live-stream-status', args=[public_stream.id]))
        self.assertEqual(public_response.status_code, status.HTTP_200_OK)
        self.assertEqual(public_response.data['id'], public_stream.id)

        private_anon_response = self.client.get(reverse('live-stream-status', args=[private_stream.id]))
        self.assertEqual(private_anon_response.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=owner)
        private_owner_response = self.client.get(reverse('live-stream-status', args=[private_stream.id]))
        self.assertEqual(private_owner_response.status_code, status.HTTP_200_OK)
        self.assertEqual(private_owner_response.data['id'], private_stream.id)

        stranger = self.create_user('status-stranger@example.com')
        self.client.force_authenticate(user=stranger)
        private_stranger_response = self.client.get(reverse('live-stream-status', args=[private_stream.id]))
        self.assertEqual(private_stranger_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_live_stream_status_endpoint_includes_contract_fields(self):
        owner = self.authenticate()
        stream = LiveStream.objects.create(
            owner=owner,
            title='Status contract stream',
            status=LiveStream.STATUS_IDLE,
        )
        response = self.client.get(reverse('live-stream-status', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in (
            'django_status',
            'effective_status',
            'status_source',
            'raw_ant_media_status',
            'can_start',
            'can_end',
            'sync_ok',
            'sync_error',
            'watch_url',
        ):
            self.assertIn(key, response.data)

    def test_live_stream_watch_url_falls_back_without_request_context(self):
        owner = self.create_user('watch-url-owner@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Watch URL stream')
        payload = LiveStreamSerializer(stream).data
        self.assertEqual(payload['watch_url'], f'/live/{stream.id}')

    @patch(
        'apps.accounts.services.AntMediaLiveAdapter.ensure_broadcast',
        return_value={'ok': True, 'stream_id': 'prepared-stream-id'},
    )
    def test_owner_can_prepare_live_stream_without_transitioning_to_live(self, _mock_ensure):
        owner = self.authenticate()
        stream = LiveStream.objects.create(
            owner=owner,
            title='Prepare stream',
            status=LiveStream.STATUS_IDLE,
            visibility=LiveStream.VISIBILITY_UNLISTED,
        )
        old_stream_key = stream.stream_key
        response = self.client.post(reverse('live-stream-prepare', args=[stream.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        for key in ('id', 'rtmp_base', 'stream_key', 'playback_url', 'watch_url', 'status', 'message', 'publish_session'):
            self.assertIn(key, response.data)
        self.assertEqual(response.data['rtmp_base'], 'rtmp://media.meownews.online/live')
        self.assertEqual(response.data['message'], 'Live stream prepared.')
        self.assertEqual(response.data['stream_key'], 'prepared-stream-id')
        self.assertNotEqual(response.data['stream_key'], old_stream_key)
        self.assertEqual(response.data['publish_session']['mode'], 'browser')
        self.assertIn('ant_media', response.data['publish_session'])
        self.assertEqual(
            response.data['publish_session']['ant_media']['stream_id'],
            response.data['stream_key'],
        )
        self.assertTrue(
            response.data['publish_session']['ant_media']['websocket_url'].endswith('/live/websocket')
        )
        self.assertTrue(
            response.data['publish_session']['ant_media']['adaptor_script_url'].endswith('/live/js/webrtc_adaptor.js')
        )
        stream.refresh_from_db()
        self.assertEqual(stream.status, LiveStream.STATUS_IDLE)
        self.assertEqual(stream.stream_key, response.data['stream_key'])

    def test_non_owner_cannot_prepare_live_stream(self):
        owner = self.create_user('prepare-owner@example.com', is_creator=True)
        stream = LiveStream.objects.create(owner=owner, title='Owner stream')
        self.authenticate(email='prepare-other@example.com')
        response = self.client.post(reverse('live-stream-prepare', args=[stream.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_REST_APP_NAME='LiveApp',
        ANT_MEDIA_SYNC_STATUS=True,
    )
    @patch('apps.accounts.services.urllib_request.urlopen')
    @patch(
        'apps.accounts.services.AntMediaLiveAdapter.ensure_broadcast',
        return_value={'ok': True, 'stream_id': 'prepared-sync-stream-id'},
    )
    def test_prepare_works_when_ant_media_sync_is_enabled(self, _mock_ensure, mock_urlopen):
        owner = self.authenticate(email='prepare-sync@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Prepare sync stream', status=LiveStream.STATUS_IDLE)
        response_payload = Mock()
        response_payload.read.return_value = b'{"status":"created"}'
        mock_urlopen.return_value.__enter__.return_value = response_payload

        response = self.client.post(reverse('live-stream-prepare', args=[stream.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'waiting_for_signal')
        self.assertEqual(response.data['stream_key'], 'prepared-sync-stream-id')
        self.assertEqual(response.data['publish_session']['ant_media']['stream_id'], 'prepared-sync-stream-id')

    def test_prepare_rejects_invalid_lifecycle_state(self):
        owner = self.authenticate(email='prepare-live@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Already live', status=LiveStream.STATUS_LIVE)
        response = self.client.post(reverse('live-stream-prepare', args=[stream.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch(
        'apps.accounts.services.AntMediaLiveAdapter.ensure_broadcast',
        return_value={
            'ok': False,
            'error': 'ant_media_create_failed',
            'message': 'Unable to create broadcast on Ant Media.',
        },
    )
    def test_prepare_returns_error_when_ant_broadcast_create_fails(self, _mock_ensure):
        owner = self.authenticate(email='prepare-create-fail@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Prepare fail stream', status=LiveStream.STATUS_IDLE)
        response = self.client.post(reverse('live-stream-prepare', args=[stream.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['error'], 'ant_media_create_failed')

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_REST_APP_NAME='LiveApp',
        ANT_MEDIA_SYNC_STATUS=True,
    )
    @patch('apps.accounts.services.urllib_request.urlopen')
    def test_live_status_api_values_contract(self, mock_urlopen):
        owner = self.authenticate()
        ready_stream = LiveStream.objects.create(
            owner=owner,
            title='Ready stream',
            status=LiveStream.STATUS_IDLE,
        )
        live_stream = LiveStream.objects.create(
            owner=owner,
            title='Live stream',
            status=LiveStream.STATUS_LIVE,
        )
        ended_stream = LiveStream.objects.create(
            owner=owner,
            title='Ended stream',
            status=LiveStream.STATUS_ENDED,
        )
        waiting_stream = LiveStream.objects.create(
            owner=owner,
            title='Waiting stream',
            status=LiveStream.STATUS_IDLE,
        )

        response_payload = Mock()
        response_payload.read.return_value = b'{"status":"created"}'
        mock_urlopen.return_value.__enter__.return_value = response_payload

        ready_response = self.client.get(reverse('live-stream-detail', args=[ready_stream.id]))
        self.assertEqual(ready_response.status_code, status.HTTP_200_OK)
        self.assertEqual(ready_response.data['status'], 'waiting_for_signal')

        with patch(
            'apps.accounts.services.AntMediaLiveAdapter._fetch_broadcast_payload',
            return_value={'payload': None, 'sync_ok': False, 'sync_error': 'ant_media_unavailable'},
        ):
            live_response = self.client.get(reverse('live-stream-detail', args=[live_stream.id]))
            ended_response = self.client.get(reverse('live-stream-detail', args=[ended_stream.id]))
            ready_fallback_response = self.client.get(reverse('live-stream-detail', args=[waiting_stream.id]))

        self.assertEqual(live_response.data['status'], 'live')
        self.assertEqual(ended_response.data['status'], 'ended')
        self.assertEqual(ready_fallback_response.data['status'], 'ready')

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_REST_APP_NAME='LiveApp',
        ANT_MEDIA_SYNC_STATUS=True,
    )
    @patch('apps.accounts.services.urllib_request.urlopen')
    def test_live_stream_status_can_sync_from_ant_media_without_mutating_db(self, mock_urlopen):
        owner = self.authenticate()
        stream = LiveStream.objects.create(
            owner=owner,
            title='Synced stream',
            status=LiveStream.STATUS_IDLE,
        )

        response_payload = Mock()
        response_payload.read.return_value = b'{"status":"broadcasting"}'
        mock_urlopen.return_value.__enter__.return_value = response_payload

        response = self.client.get(reverse('live-stream-detail', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], LiveStream.STATUS_LIVE)
        self.assertEqual(response.data['raw_ant_media_status'], 'broadcasting')
        self.assertTrue(response.data['sync_ok'])
        self.assertIsNone(response.data['sync_error'])
        self.assertEqual(response.data['status_source'], 'ant_media')
        stream.refresh_from_db()
        self.assertEqual(stream.status, LiveStream.STATUS_IDLE)
        mock_urlopen.assert_called_once_with(
            'https://ant.example.com/LiveApp/rest/v2/broadcasts/'
            f'{stream.stream_key}',
            timeout=2,
        )

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_REST_APP_NAME='LiveApp',
        ANT_MEDIA_SYNC_STATUS=True,
    )
    @patch('apps.accounts.services.urllib_request.urlopen')
    def test_live_stream_status_maps_finished_to_ended_without_mutating_db(self, mock_urlopen):
        owner = self.authenticate()
        stream = LiveStream.objects.create(
            owner=owner,
            title='Finished stream',
            status=LiveStream.STATUS_LIVE,
        )

        response_payload = Mock()
        response_payload.read.return_value = b'{"status":"finished"}'
        mock_urlopen.return_value.__enter__.return_value = response_payload

        response = self.client.get(reverse('live-stream-detail', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], LiveStream.STATUS_ENDED)
        self.assertEqual(response.data['raw_ant_media_status'], 'finished')
        self.assertEqual(response.data['status_source'], 'ant_media')
        stream.refresh_from_db()
        self.assertEqual(stream.status, LiveStream.STATUS_LIVE)

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_REST_APP_NAME='LiveApp',
        ANT_MEDIA_SYNC_STATUS=True,
    )
    @patch('apps.accounts.services.urllib_request.urlopen')
    def test_live_stream_status_waits_for_signal_when_ant_media_session_exists(self, mock_urlopen):
        owner = self.authenticate()
        stream = LiveStream.objects.create(
            owner=owner,
            title='Waiting stream',
            status=LiveStream.STATUS_IDLE,
        )

        response_payload = Mock()
        response_payload.read.return_value = b'{"status":"created"}'
        mock_urlopen.return_value.__enter__.return_value = response_payload

        response = self.client.get(reverse('live-stream-detail', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'waiting_for_signal')
        self.assertEqual(
            response.data['message'],
            'Ant Media session exists but is not yet broadcasting.',
        )
        self.assertEqual(response.data['status_source'], 'ant_media')
        stream.refresh_from_db()
        self.assertEqual(stream.status, LiveStream.STATUS_IDLE)

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_REST_APP_NAME='LiveApp',
        ANT_MEDIA_SYNC_STATUS=True,
    )
    @patch('apps.accounts.services.urllib_request.urlopen')
    def test_live_stream_viewer_count_is_normalized_from_ant_media_payload(self, mock_urlopen):
        owner = self.authenticate()
        stream = LiveStream.objects.create(
            owner=owner,
            title='Viewer count stream',
            viewer_count=7,
        )

        response_payload = Mock()
        response_payload.read.return_value = b'{"status":"broadcasting","hlsViewerCount":3,"webRTCViewerCount":2,"rtmpViewerCount":"4"}'
        mock_urlopen.return_value.__enter__.return_value = response_payload

        response = self.client.get(reverse('live-stream-detail', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['viewer_count'], 9)
        self.assertEqual(response.data['status_source'], 'ant_media')

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_REST_APP_NAME='LiveApp',
        ANT_MEDIA_SYNC_STATUS=True,
    )
    @patch('apps.accounts.services.urllib_request.urlopen', side_effect=TimeoutError())
    def test_live_stream_falls_back_when_ant_media_is_unavailable(self, _mock_urlopen):
        owner = self.authenticate()
        stream = LiveStream.objects.create(
            owner=owner,
            title='Fallback stream',
            status=LiveStream.STATUS_IDLE,
            viewer_count=5,
        )

        response = self.client.get(reverse('live-stream-detail', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], 'ready')
        self.assertEqual(response.data['status_source'], 'django_control')
        self.assertFalse(response.data['sync_ok'])
        self.assertEqual(response.data['sync_error'], 'ant_media_unavailable')
        self.assertEqual(response.data['viewer_count'], 5)

    @override_settings(
        ANT_MEDIA_PREVIEW_BASE='https://ant.example.com/live/previews',
    )
    def test_live_stream_returns_preview_urls_when_configured(self):
        self.authenticate()
        create_response = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Preview stream'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        stream = LiveStream.objects.get(pk=create_response.data['id'])
        expected_preview_url = (
            f"https://ant.example.com/live/previews/{stream.stream_key}.png"
        )
        self.assertEqual(create_response.data['thumbnail_url'], expected_preview_url)
        self.assertEqual(create_response.data['preview_image_url'], expected_preview_url)
        self.assertEqual(create_response.data['snapshot_url'], expected_preview_url)

    def test_owner_can_patch_live_stream_payment_address(self):
        self.authenticate()
        create_response = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Payment stream', 'payment_address': '0xabc123'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        stream_id = create_response.data['id']

        patch_response = self.client.patch(
            reverse('live-stream-update', args=[stream_id]),
            {'payment_address': '0xdef456'},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['payment_address'], '0xdef456')

        detail_response = self.client.get(reverse('live-stream-detail', args=[stream_id]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['payment_address'], '0xdef456')

    def test_non_owner_cannot_patch_live_stream_payment_address(self):
        self.authenticate()
        stream_id = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Owner payment stream', 'payment_address': '0xabc123'},
            format='json',
        ).data['id']

        other_user = self.create_user('other-payment@example.com')
        self.client.force_authenticate(user=other_user)
        patch_response = self.client.patch(
            reverse('live-stream-update', args=[stream_id]),
            {'payment_address': '0xdef456'},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_APP_NAME='live',
        ANT_MEDIA_RTMP_BASE='rtmp://ant.example.com/live',
        ANT_MEDIA_PLAYBACK_BASE='https://ant.example.com/live/streams',
    )
    def test_live_stream_returns_ant_media_connection_urls(self):
        self.authenticate()
        create_response = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Playback stream'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        stream = LiveStream.objects.get(pk=create_response.data['id'])
        self.assertEqual(create_response.data['rtmp_url'], 'rtmp://ant.example.com/live')
        self.assertEqual(
            create_response.data['playback_url'],
            f"https://ant.example.com/live/streams/{stream.stream_key}.m3u8",
        )
        self.assertTrue(create_response.data['playback_url'].endswith('.m3u8'))

    def test_non_owner_cannot_start_or_end_stream(self):
        owner = self.authenticate()
        stream_id = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Owner stream'},
            format='json',
        ).data['id']

        other_user = self.create_user('other-streamer@example.com', is_creator=True)
        self.client.force_authenticate(user=other_user)

        start_response = self.client.post(reverse('live-stream-start', args=[stream_id]), format='json')
        self.assertEqual(start_response.status_code, status.HTTP_404_NOT_FOUND)

        end_response = self.client.post(reverse('live-stream-end', args=[stream_id]), format='json')
        self.assertEqual(end_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_repeated_start_or_invalid_end_returns_conflict(self):
        self.authenticate()
        stream_id = self.client.post(
            reverse('live-stream-create'),
            {'title': 'Lifecycle guard stream'},
            format='json',
        ).data['id']

        first_start = self.client.post(reverse('live-stream-start', args=[stream_id]), format='json')
        self.assertEqual(first_start.status_code, status.HTTP_200_OK)
        repeated_start = self.client.post(reverse('live-stream-start', args=[stream_id]), format='json')
        self.assertEqual(repeated_start.status_code, status.HTTP_409_CONFLICT)

        first_end = self.client.post(reverse('live-stream-end', args=[stream_id]), format='json')
        self.assertEqual(first_end.status_code, status.HTTP_200_OK)
        repeated_end = self.client.post(reverse('live-stream-end', args=[stream_id]), format='json')
        self.assertEqual(repeated_end.status_code, status.HTTP_409_CONFLICT)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class SellerStoreProductAPITestCase(APITestCase):
    def create_user(self, email='seller@example.com', **extra_fields):
        defaults = {'first_name': 'Seller', 'last_name': 'User'}
        defaults.update(extra_fields)
        return User.objects.create_user(email=email, password='strong-pass-123', **defaults)

    def authenticate(self, email='seller@example.com'):
        user = self.create_user(email=email)
        self.client.force_authenticate(user=user)
        return user

    def test_owner_can_create_and_update_store(self):
        owner = self.authenticate()
        create_response = self.client.post(
            reverse('store-me'),
            {'name': 'My Store', 'slug': 'my-store', 'description': 'First store'},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data['owner_id'], owner.id)
        self.assertEqual(create_response.data['owner_name'], owner.display_name)
        self.assertEqual(create_response.data['slug'], 'my-store')

        patch_response = self.client.patch(
            reverse('store-me'),
            {'description': 'Updated description', 'is_active': False},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['description'], 'Updated description')
        self.assertFalse(patch_response.data['is_active'])

    def test_owner_can_create_update_and_delete_product(self):
        owner = self.authenticate(email='product-owner@example.com')
        store = SellerStore.objects.create(owner=owner, name='Owner Store', slug='owner-store')

        create_response = self.client.post(
            reverse('store-me-products'),
            {
                'title': 'Shirt',
                'slug': 'shirt',
                'description': 'Cotton shirt',
                'price_amount': '19.99',
                'price_currency': 'USD',
                'stock_quantity': 10,
                'status': Product.STATUS_ACTIVE,
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        product_id = create_response.data['id']
        self.assertEqual(create_response.data['store_id'], store.id)

        patch_response = self.client.patch(
            reverse('store-me-product-detail', args=[product_id]),
            {'stock_quantity': 5, 'status': Product.STATUS_INACTIVE},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['stock_quantity'], 5)
        self.assertEqual(patch_response.data['status'], Product.STATUS_INACTIVE)

        delete_response = self.client.delete(reverse('store-me-product-detail', args=[product_id]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Product.objects.filter(pk=product_id).exists())

    def test_owner_only_permissions_and_public_visibility(self):
        owner = self.create_user('owner@example.com')
        other = self.create_user('other@example.com')
        store = SellerStore.objects.create(owner=owner, name='Owner Store', slug='owner-shop', is_active=True)
        active_product = Product.objects.create(
            store=store,
            title='Active Product',
            slug='active-product',
            price_amount='10.00',
            price_currency='USD',
            stock_quantity=3,
            status=Product.STATUS_ACTIVE,
        )
        Product.objects.create(
            store=store,
            title='Draft Product',
            slug='draft-product',
            price_amount='11.00',
            price_currency='USD',
            stock_quantity=3,
            status=Product.STATUS_DRAFT,
        )

        self.client.force_authenticate(user=other)
        forbidden_response = self.client.get(reverse('store-me-product-detail', args=[active_product.id]))
        self.assertEqual(forbidden_response.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=None)
        public_store_response = self.client.get(reverse('public-store-detail', args=[store.slug]))
        self.assertEqual(public_store_response.status_code, status.HTTP_200_OK)
        public_products_response = self.client.get(reverse('public-store-products', args=[store.slug]))
        self.assertEqual(public_products_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(public_products_response.data), 1)
        self.assertEqual(public_products_response.data[0]['status'], Product.STATUS_ACTIVE)

        store.is_active = False
        store.save(update_fields=['is_active'])
        hidden_store_response = self.client.get(reverse('public-store-detail', args=[store.slug]))
        self.assertEqual(hidden_store_response.status_code, status.HTTP_404_NOT_FOUND)


class LiveStreamProductBindingAPITestCase(APITestCase):
    def create_user(self, email, is_creator=True):
        return User.objects.create_user(
            email=email,
            password='strong-pass-123',
            first_name='Live',
            last_name='Seller',
            is_creator=is_creator,
        )

    def test_owner_can_bind_product_to_own_stream(self):
        owner = self.create_user('stream-owner@example.com')
        self.client.force_authenticate(user=owner)
        store = SellerStore.objects.create(owner=owner, name='Owner Store', slug='owner-live-store')
        product = Product.objects.create(
            store=store,
            title='Bound Product',
            slug='bound-product',
            description='Shown on stream',
            price_amount='29.00',
            price_currency='USD',
            stock_quantity=5,
            status=Product.STATUS_ACTIVE,
        )
        stream = LiveStream.objects.create(owner=owner, title='Owner stream', visibility=LiveStream.VISIBILITY_PUBLIC)

        response = self.client.post(
            reverse('live-stream-products-manage', args=[stream.id]),
            {'product_id': product.id, 'sort_order': 2, 'is_pinned': True},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['sort_order'], 2)
        self.assertTrue(response.data['is_pinned'])
        self.assertEqual(response.data['product']['id'], product.id)
        self.assertEqual(response.data['product']['store']['slug'], store.slug)

    def test_cannot_bind_another_sellers_product(self):
        owner = self.create_user('stream-owner-two@example.com')
        other = self.create_user('other-seller@example.com')
        owner_store = SellerStore.objects.create(owner=owner, name='Owner Store', slug='owner-two-store')
        other_store = SellerStore.objects.create(owner=other, name='Other Store', slug='other-store')
        product = Product.objects.create(
            store=other_store,
            title='Other Product',
            slug='other-product',
            price_amount='19.00',
            price_currency='USD',
            stock_quantity=4,
            status=Product.STATUS_ACTIVE,
        )
        stream = LiveStream.objects.create(owner=owner, title='Owner stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        self.client.force_authenticate(user=owner)

        response = self.client.post(
            reverse('live-stream-products-manage', args=[stream.id]),
            {'product_id': product.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(LiveStreamProduct.objects.filter(stream=stream, product__store=owner_store).exists())

    def test_public_endpoint_returns_only_active_listings(self):
        owner = self.create_user('public-live-owner@example.com')
        store = SellerStore.objects.create(owner=owner, name='Public Store', slug='public-live-store')
        active_product = Product.objects.create(
            store=store,
            title='Active Product',
            slug='active-live-product',
            price_amount='15.00',
            price_currency='USD',
            stock_quantity=4,
            status=Product.STATUS_ACTIVE,
        )
        inactive_product = Product.objects.create(
            store=store,
            title='Inactive Product',
            slug='inactive-live-product',
            price_amount='16.00',
            price_currency='USD',
            stock_quantity=4,
            status=Product.STATUS_INACTIVE,
        )
        stream = LiveStream.objects.create(owner=owner, title='Public stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        LiveStreamProduct.objects.create(stream=stream, product=active_product, is_active=True)
        LiveStreamProduct.objects.create(stream=stream, product=inactive_product, is_active=True)
        LiveStreamProduct.objects.create(stream=stream, product=active_product, is_active=False, sort_order=9)

        response = self.client.get(reverse('live-stream-products-public', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['product']['id'], active_product.id)

    def test_sort_ordering_for_public_endpoint(self):
        owner = self.create_user('sort-owner@example.com')
        store = SellerStore.objects.create(owner=owner, name='Sort Store', slug='sort-store')
        p1 = Product.objects.create(
            store=store,
            title='Product One',
            slug='product-one',
            price_amount='10.00',
            price_currency='USD',
            stock_quantity=4,
            status=Product.STATUS_ACTIVE,
        )
        p2 = Product.objects.create(
            store=store,
            title='Product Two',
            slug='product-two',
            price_amount='11.00',
            price_currency='USD',
            stock_quantity=4,
            status=Product.STATUS_ACTIVE,
        )
        stream = LiveStream.objects.create(owner=owner, title='Sorted stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        first = LiveStreamProduct.objects.create(stream=stream, product=p1, sort_order=5, is_pinned=False)
        second = LiveStreamProduct.objects.create(stream=stream, product=p2, sort_order=1, is_pinned=True)

        response = self.client.get(reverse('live-stream-products-public', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]['binding_id'], second.id)
        self.assertEqual(response.data[1]['binding_id'], first.id)


class LiveChatAPITestCase(APITestCase):
    def create_user(self, email, is_creator=True, is_staff=False):
        return User.objects.create_user(
            email=email,
            password='strong-pass-123',
            first_name='Chat',
            last_name='User',
            is_creator=is_creator,
            is_staff=is_staff,
        )

    def test_create_and_fetch_messages(self):
        owner = self.create_user('chat-owner@example.com')
        viewer = self.create_user('chat-viewer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Chat stream', visibility=LiveStream.VISIBILITY_PUBLIC)

        self.client.force_authenticate(user=viewer)
        post_response = self.client.post(
            reverse('live-chat-messages', args=[stream.id]),
            {'message_type': 'text', 'content': 'Hello chat'},
            format='json',
        )
        self.assertEqual(post_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(post_response.data['content'], 'Hello chat')
        self.assertEqual(post_response.data['user']['id'], viewer.id)

        self.client.force_authenticate(user=None)
        get_response = self.client.get(reverse('live-chat-messages', args=[stream.id]))
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(get_response.data['results']), 1)
        self.assertEqual(get_response.data['results'][0]['content'], 'Hello chat')
        self.assertEqual(get_response.data['next_after_id'], get_response.data['results'][0]['id'])

    def test_after_id_pagination(self):
        owner = self.create_user('chat-after-owner@example.com')
        viewer = self.create_user('chat-after-viewer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='After stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        room = LiveChatRoom.objects.create(stream=stream, is_enabled=True)
        m1 = LiveChatMessage.objects.create(room=room, user=viewer, message_type='text', content='one')
        LiveChatMessage.objects.create(room=room, user=viewer, message_type='text', content='two')

        response = self.client.get(reverse('live-chat-messages', args=[stream.id]), {'after_id': m1.id, 'limit': 50})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['content'], 'two')

    def test_pin_delete_permissions(self):
        owner = self.create_user('chat-mod-owner@example.com')
        viewer = self.create_user('chat-mod-viewer@example.com')
        other = self.create_user('chat-mod-other@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Mod stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        room = LiveChatRoom.objects.create(stream=stream, is_enabled=True)
        message = LiveChatMessage.objects.create(room=room, user=viewer, message_type='text', content='mod me')

        self.client.force_authenticate(user=other)
        forbidden_pin = self.client.patch(reverse('live-chat-message-pin', args=[stream.id, message.id]), format='json')
        self.assertEqual(forbidden_pin.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=owner)
        ok_pin = self.client.patch(reverse('live-chat-message-pin', args=[stream.id, message.id]), format='json')
        self.assertEqual(ok_pin.status_code, status.HTTP_200_OK)
        self.assertTrue(ok_pin.data['is_pinned'])

        ok_delete = self.client.delete(reverse('live-chat-message-delete', args=[stream.id, message.id]))
        self.assertEqual(ok_delete.status_code, status.HTTP_204_NO_CONTENT)
        message.refresh_from_db()
        self.assertTrue(message.is_deleted)

    def test_disabled_chat_behavior(self):
        owner = self.create_user('chat-disabled-owner@example.com')
        viewer = self.create_user('chat-disabled-viewer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Disabled chat stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        LiveChatRoom.objects.create(stream=stream, is_enabled=False)

        self.client.force_authenticate(user=viewer)
        post_response = self.client.post(
            reverse('live-chat-messages', args=[stream.id]),
            {'message_type': 'text', 'content': 'blocked'},
            format='json',
        )
        self.assertEqual(post_response.status_code, status.HTTP_409_CONFLICT)

        self.client.force_authenticate(user=None)
        get_response = self.client.get(reverse('live-chat-messages', args=[stream.id]))
        self.assertEqual(get_response.status_code, status.HTTP_200_OK)
        self.assertEqual(get_response.data, {'results': [], 'next_after_id': None})

    def test_message_validation(self):
        owner = self.create_user('chat-validation-owner@example.com')
        viewer = self.create_user('chat-validation-viewer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Validation stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        self.client.force_authenticate(user=viewer)

        empty_text = self.client.post(
            reverse('live-chat-messages', args=[stream.id]),
            {'message_type': 'text', 'content': '   '},
            format='json',
        )
        self.assertEqual(empty_text.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('content', empty_text.data)

        too_long = self.client.post(
            reverse('live-chat-messages', args=[stream.id]),
            {'message_type': 'text', 'content': 'x' * 1001},
            format='json',
        )
        self.assertEqual(too_long.status_code, status.HTTP_400_BAD_REQUEST)


class LivePaymentMethodAPITestCase(APITestCase):
    def create_user(self, email, is_creator=True):
        return User.objects.create_user(
            email=email,
            password='strong-pass-123',
            first_name='Pay',
            last_name='Owner',
            is_creator=is_creator,
        )

    def test_owner_can_manage_payment_methods(self):
        owner = self.create_user('payment-owner@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Payment stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        self.client.force_authenticate(user=owner)

        create_response = self.client.post(
            reverse('live-payment-methods-manage', args=[stream.id]),
            {
                'method_type': StreamPaymentMethod.TYPE_PAY_QR,
                'title': 'Pay QR',
                'qr_text': 'pay://example',
                'wallet_address': '0xabc',
                'sort_order': 2,
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        pm_id = create_response.data['id']

        list_response = self.client.get(reverse('live-payment-methods-manage', args=[stream.id]))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)

        patch_response = self.client.patch(
            reverse('live-payment-methods-manage-detail', args=[stream.id, pm_id]),
            {'title': 'Updated Pay QR', 'is_active': False},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['title'], 'Updated Pay QR')
        self.assertFalse(patch_response.data['is_active'])

        delete_response = self.client.delete(reverse('live-payment-methods-manage-detail', args=[stream.id, pm_id]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)

    def test_public_endpoint_returns_only_active_methods(self):
        owner = self.create_user('payment-public-owner@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Payment public stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        StreamPaymentMethod.objects.create(
            stream=stream,
            method_type=StreamPaymentMethod.TYPE_WATCH_QR,
            title='Watch QR',
            qr_text='watch://qr',
            is_active=True,
            sort_order=1,
        )
        StreamPaymentMethod.objects.create(
            stream=stream,
            method_type=StreamPaymentMethod.TYPE_PAY_QR,
            title='Inactive Pay QR',
            is_active=False,
            sort_order=0,
        )

        response = self.client.get(reverse('live-payment-methods-public', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(
            set(response.data[0].keys()),
            {'id', 'method_type', 'title', 'qr_image_url', 'qr_text', 'wallet_address', 'sort_order'},
        )
        self.assertEqual(response.data[0]['method_type'], StreamPaymentMethod.TYPE_WATCH_QR)


class PaymentOrderAPITestCase(APITestCase):
    def create_user(self, email, is_creator=True, is_staff=False):
        return User.objects.create_user(
            email=email,
            password='strong-pass-123',
            first_name='Order',
            last_name='User',
            is_creator=is_creator,
            is_staff=is_staff,
        )

    def test_create_pending_tip_order(self):
        owner = self.create_user('order-owner@example.com')
        buyer = self.create_user('order-buyer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Order stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        self.client.force_authenticate(user=buyer)

        response = self.client.post(
            reverse('live-payment-order-create', args=[stream.id]),
            {'order_type': PaymentOrder.TYPE_TIP, 'amount': '5.00', 'currency': 'USD'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], PaymentOrder.STATUS_PENDING)
        self.assertEqual(response.data['order_type'], PaymentOrder.TYPE_TIP)

    def test_create_order_idempotency_reuses_existing_order(self):
        owner = self.create_user('idempotent-owner@example.com')
        buyer = self.create_user('idempotent-buyer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Idempotent stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        self.client.force_authenticate(user=buyer)

        payload = {
            'order_type': PaymentOrder.TYPE_TIP,
            'amount': '5.00',
            'currency': 'USD',
            'client_request_id': 'req-001',
        }
        first = self.client.post(reverse('live-payment-order-create', args=[stream.id]), payload, format='json')
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(reverse('live-payment-order-create', args=[stream.id]), payload, format='json')
        self.assertEqual(second.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data['id'], second.data['id'])

    def test_create_order_idempotency_rejects_payload_conflict(self):
        owner = self.create_user('idempotent-conflict-owner@example.com')
        buyer = self.create_user('idempotent-conflict-buyer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Idempotent conflict stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        self.client.force_authenticate(user=buyer)

        first = self.client.post(
            reverse('live-payment-order-create', args=[stream.id]),
            {
                'order_type': PaymentOrder.TYPE_TIP,
                'amount': '5.00',
                'currency': 'USD',
                'client_request_id': 'req-conflict',
            },
            format='json',
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        conflict = self.client.post(
            reverse('live-payment-order-create', args=[stream.id]),
            {
                'order_type': PaymentOrder.TYPE_TIP,
                'amount': '8.00',
                'currency': 'USD',
                'client_request_id': 'req-conflict',
            },
            format='json',
        )
        self.assertEqual(conflict.status_code, status.HTTP_409_CONFLICT)

    def test_create_order_validates_payment_method_and_product_binding(self):
        owner = self.create_user('validation-owner@example.com')
        buyer = self.create_user('validation-buyer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Validation stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        other_stream = LiveStream.objects.create(owner=owner, title='Other stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        store = SellerStore.objects.create(owner=owner, name='Store', slug='validation-store')
        product = Product.objects.create(
            store=store,
            title='Bound Product',
            slug='bound-product',
            price_amount='10.00',
            price_currency='USD',
            stock_quantity=10,
            status=Product.STATUS_ACTIVE,
        )
        LiveStreamProduct.objects.create(stream=stream, product=product, is_active=True)
        pm = StreamPaymentMethod.objects.create(
            stream=stream,
            method_type=StreamPaymentMethod.TYPE_PAY_QR,
            title='PM',
            is_active=True,
        )
        other_pm = StreamPaymentMethod.objects.create(
            stream=other_stream,
            method_type=StreamPaymentMethod.TYPE_PAY_QR,
            title='Other PM',
            is_active=True,
        )

        self.client.force_authenticate(user=buyer)
        valid_response = self.client.post(
            reverse('live-payment-order-create', args=[stream.id]),
            {
                'order_type': PaymentOrder.TYPE_PRODUCT,
                'amount': '10.00',
                'currency': 'USD',
                'product': product.id,
                'payment_method': pm.id,
            },
            format='json',
        )
        self.assertEqual(valid_response.status_code, status.HTTP_201_CREATED)

        invalid_pm = self.client.post(
            reverse('live-payment-order-create', args=[stream.id]),
            {
                'order_type': PaymentOrder.TYPE_PRODUCT,
                'amount': '10.00',
                'currency': 'USD',
                'product': product.id,
                'payment_method': other_pm.id,
            },
            format='json',
        )
        self.assertEqual(invalid_pm.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('payment_method', invalid_pm.data)

    def test_create_order_rejects_private_stream_for_non_owner(self):
        owner = self.create_user('private-owner@example.com')
        buyer = self.create_user('private-buyer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Private stream', visibility=LiveStream.VISIBILITY_PRIVATE)
        self.client.force_authenticate(user=buyer)

        response = self.client.post(
            reverse('live-payment-order-create', args=[stream.id]),
            {'order_type': PaymentOrder.TYPE_TIP, 'amount': '1.00', 'currency': 'USD'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_or_staff_can_mark_paid(self):
        owner = self.create_user('mark-owner@example.com')
        buyer = self.create_user('mark-buyer@example.com')
        staff = self.create_user('mark-staff@example.com', is_staff=True)
        stream = LiveStream.objects.create(owner=owner, title='Mark stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        order = PaymentOrder.objects.create(
            user=buyer,
            stream=stream,
            order_type=PaymentOrder.TYPE_TIP,
            amount='7.50',
            currency='USD',
            status=PaymentOrder.STATUS_PENDING,
        )

        self.client.force_authenticate(user=owner)
        owner_mark = self.client.post(
            reverse('live-payment-order-mark-paid', args=[stream.id, order.id]),
            {'note': 'verified on-chain'},
            format='json',
        )
        self.assertEqual(owner_mark.status_code, status.HTTP_200_OK)
        self.assertEqual(owner_mark.data['status'], PaymentOrder.STATUS_PAID)
        self.assertIsNotNone(owner_mark.data['paid_at'])
        self.assertEqual(owner_mark.data['paid_by_id'], owner.id)
        self.assertEqual(owner_mark.data['paid_note'], 'verified on-chain')

        order.status = PaymentOrder.STATUS_PENDING
        order.paid_at = None
        order.paid_by = None
        order.paid_note = ''
        order.save(update_fields=['status', 'paid_at', 'paid_by', 'paid_note'])
        self.client.force_authenticate(user=staff)
        staff_mark = self.client.post(reverse('live-payment-order-mark-paid', args=[stream.id, order.id]), format='json')
        self.assertEqual(staff_mark.status_code, status.HTTP_200_OK)
        self.assertEqual(staff_mark.data['status'], PaymentOrder.STATUS_PAID)
        self.assertEqual(staff_mark.data['paid_by_id'], staff.id)

    def test_permissions_and_visibility(self):
        owner = self.create_user('perm-owner@example.com')
        buyer = self.create_user('perm-buyer@example.com')
        other = self.create_user('perm-other@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Perm stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        order = PaymentOrder.objects.create(
            user=buyer,
            stream=stream,
            order_type=PaymentOrder.TYPE_TIP,
            amount='3.00',
            currency='USD',
        )

        self.client.force_authenticate(user=other)
        denied = self.client.get(reverse('live-payment-order-detail', args=[stream.id, order.id]))
        self.assertEqual(denied.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=buyer)
        allowed = self.client.get(reverse('live-payment-order-detail', args=[stream.id, order.id]))
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        list_response = self.client.get(reverse('account-payment-orders'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data['count'], 1)
        self.assertEqual(len(list_response.data['results']), 1)

    def test_account_payment_orders_support_filters(self):
        owner = self.create_user('filter-owner@example.com')
        buyer = self.create_user('filter-buyer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Filter stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        other_stream = LiveStream.objects.create(owner=owner, title='Filter stream 2', visibility=LiveStream.VISIBILITY_PUBLIC)
        store = SellerStore.objects.create(owner=owner, name='Filter Store', slug='filter-store')
        product = Product.objects.create(
            store=store,
            title='Filter Product',
            slug='filter-product',
            price_amount='12.00',
            price_currency='USD',
            stock_quantity=3,
            status=Product.STATUS_ACTIVE,
        )

        paid_order = PaymentOrder.objects.create(
            user=buyer,
            stream=stream,
            product=product,
            order_type=PaymentOrder.TYPE_PRODUCT,
            amount='12.00',
            currency='USD',
            status=PaymentOrder.STATUS_PAID,
        )
        PaymentOrder.objects.create(
            user=buyer,
            stream=other_stream,
            order_type=PaymentOrder.TYPE_TIP,
            amount='3.00',
            currency='USD',
            status=PaymentOrder.STATUS_PENDING,
        )

        self.client.force_authenticate(user=buyer)
        response = self.client.get(
            reverse('account-payment-orders'),
            {
                'status': PaymentOrder.STATUS_PAID,
                'live_stream': stream.id,
                'product': product.id,
                'date_from': paid_order.created_at.date().isoformat(),
                'date_to': paid_order.created_at.date().isoformat(),
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['id'], paid_order.id)

    def test_mark_paid_creates_payment_chat_message_when_room_exists(self):
        owner = self.create_user('chat-hook-owner@example.com')
        buyer = self.create_user('chat-hook-buyer@example.com')
        stream = LiveStream.objects.create(owner=owner, title='Chat hook stream', visibility=LiveStream.VISIBILITY_PUBLIC)
        room = LiveChatRoom.objects.create(stream=stream, is_enabled=True)
        order = PaymentOrder.objects.create(
            user=buyer,
            stream=stream,
            order_type=PaymentOrder.TYPE_TIP,
            amount='9.00',
            currency='USD',
            external_reference='tip-123',
        )

        self.client.force_authenticate(user=owner)
        response = self.client.post(reverse('live-payment-order-mark-paid', args=[stream.id, order.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['status'], PaymentOrder.STATUS_PAID)
        self.assertTrue(
            LiveChatMessage.objects.filter(
                room=room,
                message_type=LiveChatMessage.TYPE_PAYMENT,
                payment_reference='tip-123',
            ).exists()
        )


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class UnifiedContentMappingTestCase(APITestCase):
    def create_user(self, email='content@example.com'):
        return User.objects.create_user(email=email, password='strong-pass-123', first_name='Content', last_name='Owner')

    def test_video_maps_to_unified_content_shape(self):
        owner = self.create_user()
        video = Video.objects.create(
            owner=owner,
            title='Video content',
            description='Video body',
            category=Category.objects.get(slug='technology'),
            visibility=Video.VISIBILITY_PUBLIC,
            file=SimpleUploadedFile('unified-video.mp4', b'video-bytes', content_type='video/mp4'),
            like_count=4,
            comment_count=2,
        )

        payload = map_video_to_content(video)
        serializer = UnifiedContentSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(payload['content_type'], 'video')
        self.assertFalse(payload['is_live'])
        self.assertEqual(payload['status'], 'active')
        self.assertEqual(payload['status_source'], 'django_control')
        self.assertEqual(payload['visibility'], 'public')
        self.assertEqual(payload['like_count'], 4)
        self.assertEqual(payload['comment_count'], 2)
        self.assertIsNotNone(payload['playback_url'])
        self.assertIsNone(payload['viewer_count'])

    @override_settings(
        ANT_MEDIA_BASE_URL='https://ant.example.com',
        ANT_MEDIA_REST_APP_NAME='LiveApp',
        ANT_MEDIA_SYNC_STATUS=True,
    )
    @patch('apps.accounts.services.urllib_request.urlopen')
    def test_live_maps_to_unified_content_shape(self, mock_urlopen):
        owner = self.create_user(email='live-content@example.com')
        stream = LiveStream.objects.create(
            owner=owner,
            title='Live content',
            description='Live body',
            category=Category.objects.get(slug='gaming'),
            visibility=LiveStream.VISIBILITY_PUBLIC,
            status=LiveStream.STATUS_IDLE,
            viewer_count=1,
        )

        response_payload = Mock()
        response_payload.read.return_value = b'{"status":"broadcasting","hlsViewerCount":5}'
        mock_urlopen.return_value.__enter__.return_value = response_payload

        payload = map_live_to_content(stream)
        serializer = UnifiedContentSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(payload['content_type'], 'live')
        self.assertTrue(payload['is_live'])
        self.assertEqual(payload['status'], 'live')
        self.assertEqual(payload['status_source'], 'ant_media')
        self.assertEqual(payload['visibility'], 'public')
        self.assertEqual(payload['viewer_count'], 5)
        self.assertIsNone(payload['view_count'])
        self.assertIsNone(payload['like_count'])
        self.assertIsNone(payload['comment_count'])
