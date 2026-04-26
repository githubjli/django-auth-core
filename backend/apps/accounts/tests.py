import shutil
import tempfile
from io import StringIO
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import management
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.test import override_settings
from django.utils import timezone as django_timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.constants import BLOCKCHAIN_NAME, TOKEN_NAME, TOKEN_PEG, TOKEN_SYMBOL
from apps.accounts.content import (
    UnifiedContentSerializer,
    map_live_to_content,
    map_video_to_content,
)
from apps.accounts.models import (
    BillingPlan,
    BillingSubscription,
    Category,
    ChainReceipt,
    LiveChatMessage,
    LiveChatRoom,
    LiveStream,
    LiveStreamProduct,
    MembershipPlan,
    OrderPayment,
    PaymentOrder,
    ProductOrder,
    ProductRefundRequest,
    ProductShipment,
    Product,
    SellerPayout,
    SellerPayoutAddress,
    SellerStore,
    StreamPaymentMethod,
    UserMembership,
    UserShippingAddress,
    Video,
    WalletAddress,
)
from apps.accounts.serializers import LiveStreamSerializer
from apps.accounts.services import (
    LbryDaemonClient,
    LbryDaemonError,
    MembershipActivationService,
    PaymentDetectionService,
    ProductOrderService,
    ProductPaymentDetectionService,
    ProductPayoutService,
    get_product_wallet_send_amount,
    verify_product_qr_signature,
)

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
        self.assertEqual(
            set(me_response.data.keys()),
            {
                'id',
                'email',
                'display_name',
                'first_name',
                'last_name',
                'avatar',
                'avatar_url',
                'is_creator',
                'is_admin',
                'linked_wallet_id',
                'primary_user_address',
                'wallet_link_status',
                'linked_at',
            },
        )
        self.assertEqual(me_response.data['linked_wallet_id'], '')
        self.assertEqual(me_response.data['primary_user_address'], '')
        self.assertEqual(me_response.data['wallet_link_status'], '')
        self.assertIsNone(me_response.data['linked_at'])

    def test_me_requires_authentication(self):
        response = self.client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_me_includes_wallet_metadata_from_user(self):
        user = self.create_user('me-wallet-meta@example.com')
        user.linked_wallet_id = 'wallet-main'
        user.primary_user_address = 'bUserAddress001'
        user.wallet_link_status = User.WALLET_LINKED
        user.linked_at = datetime(2026, 1, 15, 12, 30, tzinfo=timezone.utc)
        user.save(update_fields=['linked_wallet_id', 'primary_user_address', 'wallet_link_status', 'linked_at'])
        self.client.force_authenticate(user=user)

        response = self.client.get(reverse('auth-me'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['linked_wallet_id'], 'wallet-main')
        self.assertEqual(response.data['primary_user_address'], 'bUserAddress001')
        self.assertEqual(response.data['wallet_link_status'], User.WALLET_LINKED)
        self.assertEqual(response.data['linked_at'], '2026-01-15T12:30:00Z')

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_me_reflects_latest_avatar_after_profile_update(self):
        user = self.create_user('me-avatar@example.com')
        self.client.force_authenticate(user=user)

        initial = self.client.get(reverse('auth-me'))
        self.assertEqual(initial.status_code, status.HTTP_200_OK)
        self.assertIsNone(initial.data['avatar'])
        self.assertIsNone(initial.data['avatar_url'])

        patch_response = self.client.patch(
            reverse('account-profile'),
            {'avatar': SimpleUploadedFile('avatar.png', b'avatar-bytes', content_type='image/png')},
            format='multipart',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)

        me_after_upload = self.client.get(reverse('auth-me'))
        profile_after_upload = self.client.get(reverse('account-profile'))
        self.assertEqual(me_after_upload.status_code, status.HTTP_200_OK)
        self.assertEqual(profile_after_upload.status_code, status.HTTP_200_OK)
        self.assertTrue(me_after_upload.data['avatar_url'].startswith('http://testserver/media/avatars/'))
        self.assertEqual(me_after_upload.data['avatar_url'], profile_after_upload.data['avatar_url'])

        clear_response = self.client.patch(
            reverse('account-profile'),
            {'avatar_clear': True},
            format='json',
        )
        self.assertEqual(clear_response.status_code, status.HTTP_200_OK)

        me_after_clear = self.client.get(reverse('auth-me'))
        profile_after_clear = self.client.get(reverse('account-profile'))
        self.assertIsNone(me_after_clear.data['avatar'])
        self.assertIsNone(me_after_clear.data['avatar_url'])
        self.assertEqual(me_after_clear.data['avatar_url'], profile_after_clear.data['avatar_url'])

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

    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
    def test_profile_patch_display_name_only_keeps_existing_avatar_fields(self):
        user = self.create_user('display-name-only@example.com', first_name='Old', last_name='Name')
        self.client.force_authenticate(user=user)

        upload_response = self.client.patch(
            reverse('account-profile'),
            {'avatar': SimpleUploadedFile('avatar.png', b'avatar-bytes', content_type='image/png')},
            format='multipart',
        )
        self.assertEqual(upload_response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(upload_response.data['avatar'])
        self.assertIsNotNone(upload_response.data['avatar_url'])

        display_name_only_response = self.client.patch(
            reverse('account-profile'),
            {'display_name': 'Updated Display Name'},
            format='json',
        )
        self.assertEqual(display_name_only_response.status_code, status.HTTP_200_OK)
        self.assertEqual(display_name_only_response.data['display_name'], 'Updated Display Name')
        self.assertEqual(display_name_only_response.data['first_name'], 'Updated')
        self.assertEqual(display_name_only_response.data['last_name'], 'Display Name')
        self.assertEqual(display_name_only_response.data['avatar'], upload_response.data['avatar'])
        self.assertEqual(display_name_only_response.data['avatar_url'], upload_response.data['avatar_url'])

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
        owner = self.authenticate()
        owner.avatar = SimpleUploadedFile('owner-avatar.png', b'avatar-bytes', content_type='image/png')
        owner.save(update_fields=['avatar'])
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
        self.assertTrue(detail_response.data['owner_avatar_url'].startswith('http://testserver/media/avatars/'))

        list_response = self.client.get(reverse('public-video-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertIn('count', list_response.data)
        self.assertIn('results', list_response.data)
        self.assertTrue(expected_keys.issubset(set(list_response.data['results'][0].keys())))
        self.assertTrue(list_response.data['results'][0]['owner_avatar_url'].startswith('http://testserver/media/avatars/'))

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
        self.assertTrue(summary_response.data['viewer_is_following'])
        self.assertEqual(summary_response.data['follower_count'], 1)
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
            {
                'video_id',
                'like_count',
                'comment_count',
                'viewer_has_liked',
                'viewer_is_following',
                'follower_count',
                'viewer_is_subscribed',
                'channel_id',
                'subscriber_count',
            },
        )

    def test_creator_follow_endpoints(self):
        creator = self.authenticate(email='creator-follow@example.com')
        follower = self.create_user(email='follower@example.com')
        self.client.force_authenticate(user=follower)

        follow_response = self.client.post(reverse('creator-follow', args=[creator.id]))
        self.assertEqual(follow_response.status_code, status.HTTP_200_OK)
        self.assertTrue(follow_response.data['viewer_is_following'])
        self.assertEqual(follow_response.data['follower_count'], 1)
        self.assertEqual(follow_response.data['creator_id'], creator.id)

        unfollow_response = self.client.delete(reverse('creator-follow', args=[creator.id]))
        self.assertEqual(unfollow_response.status_code, status.HTTP_200_OK)
        self.assertFalse(unfollow_response.data['viewer_is_following'])
        self.assertEqual(unfollow_response.data['follower_count'], 0)
        self.assertEqual(unfollow_response.data['creator_id'], creator.id)

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
            'id', 'owner_id', 'owner_name', 'owner_avatar_url', 'creator', 'title', 'description', 'payment_address',
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
        self.assertIn('owner_avatar_url', list_response.data[0])
        self.assertIn('creator', list_response.data[0])
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
        self.assertIn('owner_avatar_url', detail_response.data)
        self.assertEqual(detail_response.data['creator']['id'], owner.id)
        self.assertEqual(detail_response.data['stream_key'], public_stream.stream_key)

    def test_live_list_and_detail_expose_creator_avatar_when_owner_has_avatar(self):
        owner = self.create_user('avatar-streamer@example.com')
        owner.avatar = SimpleUploadedFile('owner-avatar.png', b'avatar-bytes', content_type='image/png')
        owner.save(update_fields=['avatar'])
        stream = LiveStream.objects.create(
            owner=owner,
            title='Avatar stream',
            visibility=LiveStream.VISIBILITY_PUBLIC,
        )

        list_response = self.client.get(reverse('live-stream-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data[0]['id'], stream.id)
        self.assertTrue(list_response.data[0]['owner_avatar_url'].startswith('http://testserver/media/avatars/'))
        self.assertTrue(list_response.data[0]['creator']['avatar_url'].startswith('http://testserver/media/avatars/'))

        detail_response = self.client.get(reverse('live-stream-detail', args=[stream.id]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertTrue(detail_response.data['owner_avatar_url'].startswith('http://testserver/media/avatars/'))
        self.assertTrue(detail_response.data['creator']['avatar_url'].startswith('http://testserver/media/avatars/'))

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

    def test_account_payment_orders_include_membership_fields(self):
        user = self.create_user('membership-list@example.com')
        order = PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            amount='0.00',
            currency='LBC',
            status=PaymentOrder.STATUS_PENDING,
            order_no='MO-LIST-001',
            target_type='membership_plan',
            target_id=99,
            expected_amount_lbc='30.00000000',
            actual_amount_lbc='0.00000000',
            pay_to_address='bPlatformAddressList001',
            txid='',
            confirmations=0,
        )
        self.client.force_authenticate(user=user)
        response = self.client.get(reverse('account-payment-orders'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item = response.data['results'][0]
        self.assertEqual(item['id'], order.id)
        self.assertEqual(item['order_no'], 'MO-LIST-001')
        self.assertEqual(item['order_type'], PaymentOrder.TYPE_MEMBERSHIP)
        self.assertEqual(item['currency'], 'LBC')
        self.assertEqual(item['currency_display'], TOKEN_SYMBOL)
        self.assertEqual(item['status'], PaymentOrder.STATUS_PENDING)
        self.assertEqual(item['expected_amount_lbc'], '30.00000000')
        self.assertEqual(item['actual_amount_lbc'], '0.00000000')
        self.assertEqual(item['pay_to_address'], 'bPlatformAddressList001')
        self.assertIn('txid', item)
        self.assertIn('confirmations', item)
        self.assertIn('paid_at', item)
        self.assertIn('expires_at', item)

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


class BillingAPITestCase(APITestCase):
    def create_user(self, email='billing@example.com'):
        return User.objects.create_user(email=email, password='strong-pass-123', first_name='Bill', last_name='User')

    def test_billing_plan_list_and_subscription_lifecycle(self):
        monthly = BillingPlan.objects.create(
            code='creator-monthly',
            name='Creator Monthly',
            billing_interval=BillingPlan.INTERVAL_MONTH,
            price_amount='9.99',
            price_currency='USD',
            wallet_address='bPrWVMvpgqjeViHJPKUQcKCRWRK4sLJaaa',
            is_active=True,
        )
        BillingPlan.objects.create(
            code='creator-yearly',
            name='Creator Yearly',
            billing_interval=BillingPlan.INTERVAL_YEAR,
            price_amount='99.99',
            price_currency='USD',
            is_active=False,
        )

        plans_response = self.client.get(reverse('billing-plan-list'))
        self.assertEqual(plans_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(plans_response.data), 1)
        self.assertEqual(plans_response.data[0]['id'], monthly.id)
        self.assertEqual(plans_response.data[0]['amount'], '9.99')
        self.assertEqual(plans_response.data[0]['currency'], 'USD')
        self.assertEqual(plans_response.data[0]['interval'], BillingPlan.INTERVAL_MONTH)
        self.assertIn('code', plans_response.data[0])
        self.assertIn('name', plans_response.data[0])
        self.assertIn('description', plans_response.data[0])
        self.assertEqual(plans_response.data[0]['wallet_address'], 'bPrWVMvpgqjeViHJPKUQcKCRWRK4sLJaaa')

        user = self.create_user()
        self.client.force_authenticate(user=user)

        me_empty_response = self.client.get(reverse('billing-subscription-me'))
        self.assertEqual(me_empty_response.status_code, status.HTTP_200_OK)
        self.assertIsNone(me_empty_response.data)

        create_response = self.client.post(
            reverse('billing-subscription-create'),
            {'plan_id': monthly.id},
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_response.data['status'], 'active')
        self.assertEqual(create_response.data['raw_status'], BillingSubscription.STATUS_ACTIVE)
        self.assertIn('current_period_start', create_response.data)
        self.assertIn('current_period_end', create_response.data)
        self.assertIn('cancel_at', create_response.data)
        self.assertEqual(create_response.data['plan']['interval'], BillingPlan.INTERVAL_MONTH)
        subscription_id = create_response.data['id']

        me_response = self.client.get(reverse('billing-subscription-me'))
        self.assertEqual(me_response.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(me_response.data)
        self.assertEqual(me_response.data['id'], subscription_id)

        cancel_response = self.client.post(reverse('billing-subscription-cancel', args=[subscription_id]), format='json')
        self.assertEqual(cancel_response.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_response.data['status'], 'cancel_at_period_end')
        self.assertEqual(cancel_response.data['raw_status'], BillingSubscription.STATUS_CANCELLED)
        self.assertFalse(cancel_response.data['auto_renew'])


@override_settings(LBRY_DAEMON_URL='http://127.0.0.1:5279')
class LbryDaemonClientTestCase(APITestCase):
    @patch.object(LbryDaemonClient, '_rpc_call')
    def test_address_unused_accepts_plain_string_result(self, mock_rpc_call):
        mock_rpc_call.return_value = 'bPrWVMvpgqjeViHJPKUQcKCRWRK4sLJzdQ'
        client = LbryDaemonClient()

        result = client.address_unused(wallet_id='wallet-main')
        self.assertEqual(result['address'], 'bPrWVMvpgqjeViHJPKUQcKCRWRK4sLJzdQ')

    @patch.object(LbryDaemonClient, '_rpc_call')
    def test_address_unused_rejects_empty_string_result(self, mock_rpc_call):
        mock_rpc_call.return_value = '   '
        client = LbryDaemonClient()

        with self.assertRaises(LbryDaemonError):
            client.address_unused(wallet_id='wallet-main')


@override_settings(
    LBRY_DAEMON_URL='http://127.0.0.1:5279',
    MEMBERSHIP_ORDER_EXPIRE_MINUTES=45,
)
class MembershipAPITestCase(APITestCase):
    def create_user(self, email='member@example.com'):
        return User.objects.create_user(email=email, password='strong-pass-123', first_name='Mem', last_name='Ber')

    def setUp(self):
        self.plan = MembershipPlan.objects.create(
            code=MembershipPlan.CODE_MONTHLY,
            name='Monthly',
            description='Monthly plan',
            price_lbc='12.50000000',
            duration_days=30,
            is_active=True,
            sort_order=1,
        )

    def test_membership_plan_list(self):
        response = self.client.get(reverse('membership-plan-list'))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['code'], MembershipPlan.CODE_MONTHLY)
        self.assertEqual(response.data[0]['settlement']['blockchain'], BLOCKCHAIN_NAME)
        self.assertEqual(response.data[0]['settlement']['token_name'], TOKEN_NAME)
        self.assertEqual(response.data[0]['settlement']['token_symbol'], TOKEN_SYMBOL)
        self.assertEqual(response.data[0]['settlement']['token_peg'], TOKEN_PEG)

    def test_membership_order_create_requires_authentication(self):
        response = self.client.post(
            reverse('membership-order-create'),
            {'plan_code': MembershipPlan.CODE_MONTHLY},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_membership_order_create_rejects_plan_id_only_payload(self):
        user = self.create_user('planid@example.com')
        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('membership-order-create'),
            {'plan_id': self.plan.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('plan_code', response.data)

    @override_settings(
        LBRY_PLATFORM_RECEIVE_ADDRESS='bStablePlatformAddress001',
        LBRY_PLATFORM_WALLET_ID='wallet-main',
    )
    @patch('apps.accounts.services.LbryDaemonClient.address_unused')
    def test_membership_order_create_can_use_stable_platform_receive_address(self, mock_address_unused):
        user = self.create_user('stable-address@example.com')
        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('membership-order-create'),
            {'plan_code': MembershipPlan.CODE_MONTHLY},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['pay_to_address'], 'bStablePlatformAddress001')
        mock_address_unused.assert_not_called()

    def test_membership_order_txid_hint_does_not_mark_paid(self):
        user = self.create_user('txhint@example.com')
        self.client.force_authenticate(user=user)
        order = PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            amount='0.00',
            currency='LBC',
            status=PaymentOrder.STATUS_PENDING,
            order_no='MOTXHINT001',
            pay_to_address='bHintAddress001',
            expected_amount_lbc='1.00000000',
        )
        response = self.client.post(
            reverse('membership-order-tx-hint', args=[order.order_no]),
            {'txid': 'hinted-tx-123'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.txid, 'hinted-tx-123')
        self.assertEqual(order.status, PaymentOrder.STATUS_PENDING)
        self.assertIn('verification', response.data['detail'])

    @patch('apps.accounts.services.LbryDaemonClient.address_unused')
    def test_create_membership_order_assigns_wallet_address_and_snapshots(self, mock_address_unused):
        mock_address_unused.return_value = {
            'address': 'bTestLbcAddressForOrder1',
            'wallet_id': 'wallet-main',
            'account_id': 'account-main',
        }
        user = self.create_user()
        self.client.force_authenticate(user=user)

        response = self.client.post(
            reverse('membership-order-create'),
            {'plan_code': MembershipPlan.CODE_MONTHLY},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['status'], PaymentOrder.STATUS_PENDING)
        self.assertEqual(response.data['expected_amount_lbc'], '12.50000000')
        self.assertEqual(response.data['settlement']['blockchain'], BLOCKCHAIN_NAME)
        self.assertEqual(response.data['settlement']['token_name'], TOKEN_NAME)
        self.assertEqual(response.data['settlement']['token_symbol'], TOKEN_SYMBOL)
        self.assertEqual(response.data['settlement']['token_peg'], TOKEN_PEG)
        self.assertEqual(response.data['pay_to_address'], 'bTestLbcAddressForOrder1')
        self.assertEqual(response.data['qr_text'], 'bTestLbcAddressForOrder1')
        self.assertTrue(response.data['order_no'])

        order = PaymentOrder.objects.get(order_no=response.data['order_no'])
        self.assertEqual(order.user_id, user.id)
        self.assertEqual(order.order_type, PaymentOrder.TYPE_MEMBERSHIP)
        self.assertEqual(order.target_type, 'membership_plan')
        self.assertEqual(order.target_id, self.plan.id)
        self.assertEqual(order.plan_code_snapshot, self.plan.code)
        self.assertEqual(order.plan_name_snapshot, self.plan.name)
        self.assertEqual(str(order.expected_amount_lbc), '12.50000000')
        self.assertEqual(order.pay_to_address, 'bTestLbcAddressForOrder1')
        self.assertIsNotNone(order.expires_at)
        self.assertIsNotNone(order.wallet_address_id)
        self.assertEqual(order.wallet_address.usage_type, WalletAddress.USAGE_MEMBERSHIP)
        self.assertEqual(order.wallet_address.status, WalletAddress.STATUS_ASSIGNED)
        self.assertEqual(order.wallet_address.wallet_id, 'wallet-main')
        self.assertEqual(order.wallet_address.account_id, 'account-main')
        self.assertEqual(order.wallet_address.assigned_order_id, order.id)
        mock_address_unused.assert_called_once()

        detail_response = self.client.get(reverse('membership-order-detail', args=[order.order_no]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['order_no'], order.order_no)
        self.assertEqual(detail_response.data['settlement']['token_symbol'], TOKEN_SYMBOL)

    @override_settings(
        LBRY_PLATFORM_WALLET_ID='wallet-main',
        LBRY_PLATFORM_ACCOUNT_ID='   ',
    )
    @patch('apps.accounts.services.LbryDaemonClient.address_unused')
    def test_create_membership_order_does_not_send_blank_account_id(self, mock_address_unused):
        mock_address_unused.return_value = {
            'address': 'bNoBlankAccountAddress',
            'wallet_id': 'wallet-main',
        }
        user = self.create_user('blank-account@example.com')
        self.client.force_authenticate(user=user)

        response = self.client.post(
            reverse('membership-order-create'),
            {'plan_code': MembershipPlan.CODE_MONTHLY},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_address_unused.assert_called_once_with(wallet_id='wallet-main', account_id=None)

    @patch('apps.accounts.services.LbryDaemonClient.address_unused')
    def test_duplicate_assigned_address_fails_safely(self, mock_address_unused):
        owner = self.create_user('existing-order-owner@example.com')
        existing_order = PaymentOrder.objects.create(
            user=owner,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            amount='0.00',
            currency='LBC',
            status=PaymentOrder.STATUS_PENDING,
            order_no='MOEXISTING001',
        )
        WalletAddress.objects.create(
            address='bDuplicateAddress',
            usage_type=WalletAddress.USAGE_MEMBERSHIP,
            status=WalletAddress.STATUS_ASSIGNED,
            assigned_order=existing_order,
        )
        mock_address_unused.return_value = {'address': 'bDuplicateAddress'}

        buyer = self.create_user('member-buyer@example.com')
        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('membership-order-create'),
            {'plan_code': MembershipPlan.CODE_MONTHLY},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn('temporarily unavailable', response.data['detail'])

    def test_membership_me_shape(self):
        user = self.create_user('membership-me@example.com')
        self.client.force_authenticate(user=user)

        empty_response = self.client.get(reverse('membership-me'))
        self.assertEqual(empty_response.status_code, status.HTTP_200_OK)
        self.assertEqual(empty_response.data['status'], 'none')
        self.assertIsNone(empty_response.data['plan'])

        order = PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            amount='0.00',
            currency='LBC',
            status=PaymentOrder.STATUS_PENDING,
            order_no='MOME0001',
        )
        UserMembership.objects.create(
            user=user,
            source_order=order,
            plan=self.plan,
            status=UserMembership.STATUS_ACTIVE,
            starts_at=datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
            ends_at=datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc),
        )

        active_response = self.client.get(reverse('membership-me'))
        self.assertEqual(active_response.status_code, status.HTTP_200_OK)
        self.assertEqual(active_response.data['status'], UserMembership.STATUS_ACTIVE)
        self.assertEqual(active_response.data['plan']['code'], self.plan.code)


@override_settings(
    LBRY_DAEMON_URL='http://127.0.0.1:5279',
    PRODUCT_PLATFORM_RECEIVE_ADDRESS='bProductPlatformAddress001',
)
class WalletPrototypeAPITestCase(APITestCase):
    def create_user(self, email='walletproto@example.com'):
        return User.objects.create_user(email=email, password='strong-pass-123', first_name='Wallet', last_name='Proto')

    def create_plan(self):
        return MembershipPlan.objects.create(
            code='walletproto-monthly',
            name='WalletProto Monthly',
            price_lbc='30.00000000',
            duration_days=30,
            is_active=True,
            sort_order=1,
        )

    def create_order(self, *, user, plan, status=PaymentOrder.STATUS_PENDING):
        return PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            target_type='membership_plan',
            target_id=plan.id,
            plan_code_snapshot=plan.code,
            plan_name_snapshot=plan.name,
            expected_amount_lbc=plan.price_lbc,
            amount='0.00',
            currency='LBC',
            status=status,
            order_no=f'MOWALLET{PaymentOrder.objects.count()+1:03d}',
            pay_to_address='bPlatformReceiveAddress001',
        )

    def create_store_product(self, owner_email='wallet-seller@example.com', slug='wallet-seller-store'):
        seller = self.create_user(owner_email)
        store = SellerStore.objects.create(owner=seller, name='Wallet Seller Store', slug=slug, is_active=True)
        product = Product.objects.create(
            store=store,
            title='Wallet Product',
            slug=f'wallet-product-{store.id}',
            price_amount='9.50',
            price_currency='USD',
            stock_quantity=10,
            status=Product.STATUS_ACTIVE,
        )
        return seller, store, product

    def create_shipping_address(self, buyer):
        return UserShippingAddress.objects.create(
            user=buyer,
            receiver_name='Buyer Receiver',
            phone='0800000000',
            country='Thailand',
            province='Bangkok',
            city='Bangkok',
            district='Pathum Wan',
            street_address='123 Main',
            postal_code='10330',
            is_default=True,
        )

    def create_product_order(self, buyer, product, shipping_address):
        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('product-order-list-create'),
            {'product_id': product.id, 'quantity': 1, 'shipping_address_id': shipping_address.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order = ProductOrder.objects.get(order_no=response.data['order_no'])
        return order, order.payment_order

    def test_unauthenticated_access_blocked(self):
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {'order_no': 'MO1', 'wallet_id': 'wallet-main', 'password': 'secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    @patch('apps.accounts.views.WalletPrototypePayOrderService.pay_payment_order')
    def test_membership_endpoint_uses_shared_pay_payment_order_method(self, mock_pay_payment_order):
        user = self.create_user('shared-membership@example.com')
        user.linked_wallet_id = 'wallet-main'
        user.save(update_fields=['linked_wallet_id'])
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan)
        mock_pay_payment_order.return_value = {'order_no': order.order_no, 'txid': 'tx-shared-membership', 'wallet_relocked': True}

        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {'order_no': order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_pay_payment_order.assert_called_once()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    def test_pay_order_uses_backend_order_amount_and_address(self, mock_tx_show, mock_unlock, mock_send, mock_lock):
        user = self.create_user('payorder@example.com')
        user.linked_wallet_id = 'wallet-main'
        user.save(update_fields=['linked_wallet_id'])
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan)
        mock_unlock.return_value = True
        mock_send.return_value = {'txid': 'tx-wallet-001'}
        mock_tx_show.return_value = {
            'txid': 'tx-wallet-001',
            'confirmations': 2,
            'outputs': [{'nout': 0, 'address': order.pay_to_address, 'amount': '30.0'}],
        }

        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {
                'order_no': order.order_no,
                'wallet_id': 'wallet-main',
                'password': 'temporary-secret',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(str(kwargs['amount']), str(order.expected_amount_lbc))
        self.assertEqual(kwargs['addresses'], [order.pay_to_address])
        self.assertEqual(response.data['txid'], 'tx-wallet-001')
        order.refresh_from_db()
        self.assertEqual(order.txid, 'tx-wallet-001')
        self.assertEqual(order.status, PaymentOrder.STATUS_PAID)
        self.assertFalse(hasattr(order, 'password'))
        self.assertTrue(response.data['verification']['verified'])
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_wallet_lock_attempted_even_when_send_fails(self, mock_unlock, mock_send, mock_lock):
        user = self.create_user('sendfail@example.com')
        user.linked_wallet_id = 'wallet-main'
        user.save(update_fields=['linked_wallet_id'])
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan)
        mock_unlock.return_value = True
        mock_send.side_effect = LbryDaemonError('send failed')

        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {'order_no': order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()

    @patch('apps.accounts.services.logger.info')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_wallet_unlock_dict_result_true_allows_send_and_password_not_logged(self, mock_unlock, mock_send, mock_lock, mock_logger_info):
        user = self.create_user('unlock-dict-true@example.com')
        user.linked_wallet_id = 'wallet-main'
        user.save(update_fields=['linked_wallet_id'])
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan)
        mock_unlock.return_value = {'result': True}
        mock_send.return_value = {'txid': 'tx-wallet-unlock-dict'}

        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {'order_no': order.order_no, 'wallet_id': 'wallet-main', 'password': 'secret-password-value'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_send.assert_called_once()
        for call in mock_logger_info.call_args_list:
            rendered = ' '.join(str(arg) for arg in call.args)
            self.assertNotIn('secret-password-value', rendered)

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_wallet_unlock_false_blocks_send(self, mock_unlock, mock_send, mock_lock):
        user = self.create_user('unlock-false@example.com')
        user.linked_wallet_id = 'wallet-main'
        user.save(update_fields=['linked_wallet_id'])
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan)
        mock_unlock.return_value = False

        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {'order_no': order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_wallet_unlock_dict_result_false_blocks_send(self, mock_unlock, mock_send, mock_lock):
        user = self.create_user('unlock-dict-false@example.com')
        user.linked_wallet_id = 'wallet-main'
        user.save(update_fields=['linked_wallet_id'])
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan)
        mock_unlock.return_value = {'result': False}

        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {'order_no': order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_send_success_lock_fail_returns_success_with_warning(self, mock_unlock, mock_send, mock_lock):
        user = self.create_user('lockfail@example.com')
        user.linked_wallet_id = 'wallet-main'
        user.save(update_fields=['linked_wallet_id'])
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan)
        mock_unlock.return_value = True
        mock_send.return_value = {'txid': 'tx-wallet-002'}
        mock_lock.side_effect = LbryDaemonError('lock failed')

        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {'order_no': order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['txid'], 'tx-wallet-002')
        self.assertEqual(response.data['warning'], 'wallet_lock_failed')

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_user_cannot_pay_another_users_order(self, mock_unlock, mock_send, mock_lock):
        owner = self.create_user('owner@example.com')
        owner.linked_wallet_id = 'wallet-main'
        owner.save(update_fields=['linked_wallet_id'])
        other = self.create_user('other@example.com')
        other.linked_wallet_id = 'wallet-main'
        other.save(update_fields=['linked_wallet_id'])
        plan = self.create_plan()
        order = self.create_order(user=owner, plan=plan)

        self.client.force_authenticate(user=other)
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {'order_no': order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    def test_expired_order_rejected(self):
        user = self.create_user('expired-proto@example.com')
        user.linked_wallet_id = 'wallet-main'
        user.save(update_fields=['linked_wallet_id'])
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan, status=PaymentOrder.STATUS_PENDING)
        order.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        order.save(update_fields=['expires_at', 'updated_at'])

        self.client.force_authenticate(user=user)
        response = self.client.post(
            reverse('wallet-prototype-pay-order'),
            {'order_no': order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('expired', response.data['detail'])

    @override_settings(PRODUCT_WALLET_PAYMENT_TREAT_THB_LTT_AS_NATIVE=True)
    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_buyer_can_submit_product_order_wallet_payment_without_marking_paid(
        self,
        mock_unlock,
        mock_send,
        mock_lock,
        mock_tx_show,
    ):
        buyer = self.create_user('wallet-product-buyer@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-1')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('3.25000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])
        mock_send.return_value = {'txid': 'tx-product-wallet-001'}

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['order_no'], product_order.order_no)
        self.assertEqual(response.data['txid'], 'tx-product-wallet-001')
        self.assertEqual(response.data['message'], 'Payment submitted. Waiting for blockchain confirmation.')
        self.assertTrue(response.data['wallet_relocked'])
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['addresses'], [payment_order.pay_to_address])
        self.assertEqual(str(kwargs['amount']), '3.25000000')
        payment_order.refresh_from_db()
        product_order.refresh_from_db()
        self.assertEqual(payment_order.txid, 'tx-product-wallet-001')
        self.assertEqual(payment_order.status, PaymentOrder.STATUS_PENDING)
        self.assertEqual(product_order.status, ProductOrder.STATUS_PENDING_PAYMENT)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()
        mock_tx_show.assert_not_called()

    @override_settings(PRODUCT_WALLET_PAYMENT_TREAT_THB_LTT_AS_NATIVE=True)
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_non_buyer_cannot_pay_another_users_product_order(self, mock_unlock, mock_send, mock_lock):
        owner = self.create_user('wallet-product-owner@example.com')
        owner.linked_wallet_id = 'wallet-main'
        owner.save(update_fields=['linked_wallet_id'])
        attacker = self.create_user('wallet-product-attacker@example.com')
        attacker.linked_wallet_id = 'wallet-main'
        attacker.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-2')
        shipping = self.create_shipping_address(owner)
        product_order, _ = self.create_product_order(owner, product, shipping)

        self.client.force_authenticate(user=attacker)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @override_settings(PRODUCT_WALLET_PAYMENT_TREAT_THB_LTT_AS_NATIVE=True)
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_payment_missing_pay_to_address_returns_validation_error(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-noaddr@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-3')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.pay_to_address = ''
        payment_order.save(update_fields=['pay_to_address', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('missing payment amount/address', response.data['detail'])
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    def test_product_wallet_payment_thb_ltt_native_disabled_returns_validation_error(self):
        buyer = self.create_user('wallet-product-native-disabled@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-native-disabled')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data['detail'],
            'Product wallet payment requires THB-LTT token transfer support; native wallet_send cannot send THB-LTT.',
        )

    def test_product_wallet_payment_missing_linked_wallet_returns_400(self):
        buyer = self.create_user('wallet-product-nowallet@example.com')
        _, _, product = self.create_store_product(slug='wallet-product-store-4')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Missing linked wallet.')

    def test_product_wallet_payment_missing_password_validation_error(self):
        buyer = self.create_user('wallet-product-nopassword@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-5')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_product_wallet_payment_non_pending_order_returns_409(self):
        buyer = self.create_user('wallet-product-nonpending@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-7')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        product_order.status = ProductOrder.STATUS_PAID
        product_order.save(update_fields=['status', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @override_settings(PRODUCT_WALLET_PAYMENT_TREAT_THB_LTT_AS_NATIVE=True)
    def test_get_product_wallet_send_amount_prefers_expected_amount_field(self):
        buyer = self.create_user('helper-amount-buyer@example.com')
        _, _, product = self.create_store_product(slug='wallet-helper-store')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('7.77000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])

        amount = get_product_wallet_send_amount(payment_order=payment_order, product_order=product_order)
        self.assertEqual(amount, Decimal('7.77000000'))

    @override_settings(PRODUCT_WALLET_PAYMENT_TREAT_THB_LTT_AS_NATIVE=True)
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_lock_attempted_after_send_failure(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-sendfail@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-6')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_send.side_effect = LbryDaemonError('send failed')

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()

    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_buyer_can_submit_product_order_wallet_payment_without_marking_paid(
        self,
        mock_unlock,
        mock_send,
        mock_lock,
        mock_tx_show,
    ):
        buyer = self.create_user('wallet-product-buyer@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-1')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = None
        payment_order.amount = product_order.total_amount
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])
        mock_send.return_value = {'txid': 'tx-product-wallet-001'}

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['order_no'], product_order.order_no)
        self.assertEqual(response.data['txid'], 'tx-product-wallet-001')
        self.assertEqual(response.data['message'], 'Payment submitted. Waiting for blockchain confirmation.')
        self.assertTrue(response.data['wallet_relocked'])
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['addresses'], [payment_order.pay_to_address])
        self.assertEqual(str(kwargs['amount']), str(product_order.total_amount))
        payment_order.refresh_from_db()
        product_order.refresh_from_db()
        self.assertEqual(payment_order.txid, 'tx-product-wallet-001')
        self.assertEqual(payment_order.status, PaymentOrder.STATUS_PENDING)
        self.assertEqual(product_order.status, ProductOrder.STATUS_PENDING_PAYMENT)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()
        mock_tx_show.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_non_buyer_cannot_pay_another_users_product_order(self, mock_unlock, mock_send, mock_lock):
        owner = self.create_user('wallet-product-owner@example.com')
        owner.linked_wallet_id = 'wallet-main'
        owner.save(update_fields=['linked_wallet_id'])
        attacker = self.create_user('wallet-product-attacker@example.com')
        attacker.linked_wallet_id = 'wallet-main'
        attacker.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-2')
        shipping = self.create_shipping_address(owner)
        product_order, _ = self.create_product_order(owner, product, shipping)

        self.client.force_authenticate(user=attacker)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_payment_missing_pay_to_address_returns_validation_error(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-noaddr@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-3')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.pay_to_address = ''
        payment_order.save(update_fields=['pay_to_address', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('missing payment amount/address', response.data['detail'])
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    def test_product_wallet_payment_missing_linked_wallet_returns_400(self):
        buyer = self.create_user('wallet-product-nowallet@example.com')
        _, _, product = self.create_store_product(slug='wallet-product-store-4')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Missing linked wallet.')

    def test_product_wallet_payment_missing_password_validation_error(self):
        buyer = self.create_user('wallet-product-nopassword@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-5')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_product_wallet_payment_non_pending_order_returns_409(self):
        buyer = self.create_user('wallet-product-nonpending@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-7')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        product_order.status = ProductOrder.STATUS_PAID
        product_order.save(update_fields=['status', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_lock_attempted_after_send_failure(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-sendfail@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-6')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_send.side_effect = LbryDaemonError('send failed')

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()

    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_buyer_can_submit_product_order_wallet_payment_without_marking_paid(
        self,
        mock_unlock,
        mock_send,
        mock_lock,
        mock_tx_show,
    ):
        buyer = self.create_user('wallet-product-buyer@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-1')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('3.25000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])
        mock_send.return_value = {'txid': 'tx-product-wallet-001'}

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['order_no'], product_order.order_no)
        self.assertEqual(response.data['txid'], 'tx-product-wallet-001')
        self.assertEqual(response.data['message'], 'Payment submitted. Waiting for blockchain confirmation.')
        self.assertTrue(response.data['wallet_relocked'])
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['addresses'], [payment_order.pay_to_address])
        self.assertEqual(str(kwargs['amount']), '3.25000000')
        payment_order.refresh_from_db()
        product_order.refresh_from_db()
        self.assertEqual(payment_order.txid, 'tx-product-wallet-001')
        self.assertEqual(payment_order.status, PaymentOrder.STATUS_PENDING)
        self.assertEqual(product_order.status, ProductOrder.STATUS_PENDING_PAYMENT)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()
        mock_tx_show.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_non_buyer_cannot_pay_another_users_product_order(self, mock_unlock, mock_send, mock_lock):
        owner = self.create_user('wallet-product-owner@example.com')
        owner.linked_wallet_id = 'wallet-main'
        owner.save(update_fields=['linked_wallet_id'])
        attacker = self.create_user('wallet-product-attacker@example.com')
        attacker.linked_wallet_id = 'wallet-main'
        attacker.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-2')
        shipping = self.create_shipping_address(owner)
        product_order, _ = self.create_product_order(owner, product, shipping)

        self.client.force_authenticate(user=attacker)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_payment_missing_pay_to_address_returns_validation_error(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-noaddr@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-3')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.pay_to_address = ''
        payment_order.save(update_fields=['pay_to_address', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('missing payment amount/address', response.data['detail'])
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @override_settings(PRODUCT_WALLET_PAYMENT_TREAT_THB_LTT_AS_NATIVE=False)
    def test_product_wallet_payment_thb_ltt_native_disabled_returns_validation_error(self):
        buyer = self.create_user('wallet-product-native-disabled@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-native-disabled')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.data['detail'],
            'Product wallet payment for THB-LTT is disabled by configuration.',
        )

    def test_product_wallet_payment_missing_linked_wallet_returns_400(self):
        buyer = self.create_user('wallet-product-nowallet@example.com')
        _, _, product = self.create_store_product(slug='wallet-product-store-4')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Missing linked wallet.')

    def test_product_wallet_payment_missing_password_validation_error(self):
        buyer = self.create_user('wallet-product-nopassword@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-5')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_product_wallet_payment_non_pending_order_returns_409(self):
        buyer = self.create_user('wallet-product-nonpending@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-7')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        product_order.status = ProductOrder.STATUS_PAID
        product_order.save(update_fields=['status', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_get_product_wallet_send_amount_prefers_expected_amount_field(self):
        buyer = self.create_user('helper-amount-buyer@example.com')
        _, _, product = self.create_store_product(slug='wallet-helper-store')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('7.77000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])

        amount = get_product_wallet_send_amount(payment_order=payment_order, product_order=product_order)
        self.assertEqual(amount, Decimal('7.77000000'))

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_lock_attempted_after_send_failure(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-sendfail@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-6')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_send.side_effect = LbryDaemonError('send failed')

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()

    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_buyer_can_submit_product_order_wallet_payment_without_marking_paid(
        self,
        mock_unlock,
        mock_send,
        mock_lock,
        mock_tx_show,
    ):
        buyer = self.create_user('wallet-product-buyer@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-1')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('3.25000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])
        mock_send.return_value = {'txid': 'tx-product-wallet-001'}

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['order_no'], product_order.order_no)
        self.assertEqual(response.data['txid'], 'tx-product-wallet-001')
        self.assertEqual(response.data['message'], 'Payment submitted. Waiting for blockchain confirmation.')
        self.assertTrue(response.data['wallet_relocked'])
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['addresses'], [payment_order.pay_to_address])
        self.assertEqual(str(kwargs['amount']), '3.25000000')
        payment_order.refresh_from_db()
        product_order.refresh_from_db()
        self.assertEqual(payment_order.txid, 'tx-product-wallet-001')
        self.assertEqual(payment_order.status, PaymentOrder.STATUS_PENDING)
        self.assertEqual(product_order.status, ProductOrder.STATUS_PENDING_PAYMENT)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()
        mock_tx_show.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_non_buyer_cannot_pay_another_users_product_order(self, mock_unlock, mock_send, mock_lock):
        owner = self.create_user('wallet-product-owner@example.com')
        owner.linked_wallet_id = 'wallet-main'
        owner.save(update_fields=['linked_wallet_id'])
        attacker = self.create_user('wallet-product-attacker@example.com')
        attacker.linked_wallet_id = 'wallet-main'
        attacker.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-2')
        shipping = self.create_shipping_address(owner)
        product_order, _ = self.create_product_order(owner, product, shipping)

        self.client.force_authenticate(user=attacker)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_payment_missing_pay_to_address_returns_validation_error(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-noaddr@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-3')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.pay_to_address = ''
        payment_order.save(update_fields=['pay_to_address', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('missing pay_to_address', response.data['detail'])
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.views.WalletPrototypePayOrderService.pay_payment_order')
    def test_product_endpoint_uses_shared_pay_payment_order_method(self, mock_pay_payment_order):
        buyer = self.create_user('shared-product-buyer@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-shared-product-store')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('2.50000000')
        payment_order.save(update_fields=['expected_amount_lbc', 'updated_at'])
        mock_pay_payment_order.return_value = {
            'order_no': payment_order.order_no,
            'txid': 'tx-shared-product',
            'wallet_relocked': True,
        }

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['txid'], 'tx-shared-product')
        kwargs = mock_pay_payment_order.call_args.kwargs
        self.assertEqual(kwargs['amount_override'], Decimal('2.50000000'))
        self.assertEqual(kwargs['order'], payment_order)

    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_locked_wallet_error_returns_clear_detail(self, mock_unlock, mock_send):
        buyer = self.create_user('product-locked-wallet@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-locked-wallet-store')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_send.side_effect = LbryDaemonError('Cannot spend funds with locked wallet, unlock first.')

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn('locked wallet', response.data['detail'])

    def test_product_wallet_payment_missing_linked_wallet_returns_400(self):
        buyer = self.create_user('wallet-product-nowallet@example.com')
        _, _, product = self.create_store_product(slug='wallet-product-store-4')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Missing linked wallet.')

    def test_product_wallet_payment_missing_password_validation_error(self):
        buyer = self.create_user('wallet-product-nopassword@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-5')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_product_wallet_payment_non_pending_order_returns_409(self):
        buyer = self.create_user('wallet-product-nonpending@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-7')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        product_order.status = ProductOrder.STATUS_PAID
        product_order.save(update_fields=['status', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_get_product_wallet_send_amount_prefers_expected_amount_field(self):
        buyer = self.create_user('helper-amount-buyer@example.com')
        _, _, product = self.create_store_product(slug='wallet-helper-store')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('7.77000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])

        amount = get_product_wallet_send_amount(payment_order=payment_order, product_order=product_order)
        self.assertEqual(amount, Decimal('7.77000000'))

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_lock_attempted_after_send_failure(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-sendfail@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-6')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_send.side_effect = LbryDaemonError('send failed')

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()

    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_buyer_can_submit_product_order_wallet_payment_without_marking_paid(
        self,
        mock_unlock,
        mock_send,
        mock_lock,
        mock_tx_show,
    ):
        buyer = self.create_user('wallet-product-buyer@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-1')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('3.25000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])
        mock_send.return_value = {'txid': 'tx-product-wallet-001'}

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['order_no'], product_order.order_no)
        self.assertEqual(response.data['txid'], 'tx-product-wallet-001')
        self.assertEqual(response.data['message'], 'Payment submitted. Waiting for blockchain confirmation.')
        self.assertTrue(response.data['wallet_relocked'])
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['addresses'], [payment_order.pay_to_address])
        self.assertEqual(str(kwargs['amount']), '3.25000000')
        payment_order.refresh_from_db()
        product_order.refresh_from_db()
        self.assertEqual(payment_order.txid, 'tx-product-wallet-001')
        self.assertEqual(payment_order.status, PaymentOrder.STATUS_PENDING)
        self.assertEqual(product_order.status, ProductOrder.STATUS_PENDING_PAYMENT)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()
        mock_tx_show.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_non_buyer_cannot_pay_another_users_product_order(self, mock_unlock, mock_send, mock_lock):
        owner = self.create_user('wallet-product-owner@example.com')
        owner.linked_wallet_id = 'wallet-main'
        owner.save(update_fields=['linked_wallet_id'])
        attacker = self.create_user('wallet-product-attacker@example.com')
        attacker.linked_wallet_id = 'wallet-main'
        attacker.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-2')
        shipping = self.create_shipping_address(owner)
        product_order, _ = self.create_product_order(owner, product, shipping)

        self.client.force_authenticate(user=attacker)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_payment_missing_pay_to_address_returns_validation_error(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-noaddr@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-3')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.pay_to_address = ''
        payment_order.save(update_fields=['pay_to_address', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('missing pay_to_address', response.data['detail'])
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.views.WalletPrototypePayOrderService.pay_payment_order')
    def test_product_endpoint_uses_shared_pay_payment_order_method(self, mock_pay_payment_order):
        buyer = self.create_user('shared-product-buyer@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-shared-product-store')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('2.50000000')
        payment_order.save(update_fields=['expected_amount_lbc', 'updated_at'])
        mock_pay_payment_order.return_value = {
            'order_no': payment_order.order_no,
            'txid': 'tx-shared-product',
            'wallet_relocked': True,
        }

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['txid'], 'tx-shared-product')
        kwargs = mock_pay_payment_order.call_args.kwargs
        self.assertEqual(kwargs['amount_override'], Decimal('2.50000000'))
        self.assertEqual(kwargs['order'], payment_order)

    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_locked_wallet_error_returns_clear_detail(self, mock_unlock, mock_send):
        buyer = self.create_user('product-locked-wallet@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-locked-wallet-store')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_send.side_effect = LbryDaemonError('Cannot spend funds with locked wallet, unlock first.')

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn('locked wallet', response.data['detail'])

    def test_product_wallet_payment_missing_linked_wallet_returns_400(self):
        buyer = self.create_user('wallet-product-nowallet@example.com')
        _, _, product = self.create_store_product(slug='wallet-product-store-4')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Missing linked wallet.')

    def test_product_wallet_payment_missing_password_validation_error(self):
        buyer = self.create_user('wallet-product-nopassword@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-5')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_product_wallet_payment_non_pending_order_returns_409(self):
        buyer = self.create_user('wallet-product-nonpending@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-7')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        product_order.status = ProductOrder.STATUS_PAID
        product_order.save(update_fields=['status', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_product_wallet_payment_missing_expected_amount_returns_validation_error(self):
        buyer = self.create_user('wallet-product-noexpected@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-noexpected')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = None
        payment_order.save(update_fields=['expected_amount_lbc', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('missing expected_amount_lbc', response.data['detail'])

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_duplicate_product_payment_does_not_trigger_second_wallet_send(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-duplicate@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-duplicate')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_send.return_value = {'txid': 'tx-product-duplicate-001'}

        self.client.force_authenticate(user=buyer)
        first = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        second = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second.data['txid'], 'tx-product-duplicate-001')
        self.assertEqual(mock_send.call_count, 1)

    def test_get_product_wallet_send_amount_prefers_expected_amount_field(self):
        buyer = self.create_user('helper-amount-buyer@example.com')
        _, _, product = self.create_store_product(slug='wallet-helper-store')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('7.77000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])

        amount = get_product_wallet_send_amount(payment_order=payment_order, product_order=product_order)
        self.assertEqual(amount, Decimal('7.77000000'))

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_lock_attempted_after_send_failure(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-sendfail@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-6')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_send.side_effect = LbryDaemonError('send failed')

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()

    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_buyer_can_submit_product_order_wallet_payment_without_marking_paid(
        self,
        mock_unlock,
        mock_send,
        mock_lock,
        mock_tx_show,
    ):
        buyer = self.create_user('wallet-product-buyer@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-1')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        mock_unlock.return_value = True
        payment_order.expected_amount_lbc = Decimal('3.25000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])
        mock_send.return_value = {'txid': 'tx-product-wallet-001'}

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['order_no'], product_order.order_no)
        self.assertEqual(response.data['txid'], 'tx-product-wallet-001')
        self.assertEqual(response.data['message'], 'Payment submitted. Waiting for blockchain confirmation.')
        self.assertTrue(response.data['wallet_relocked'])
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['addresses'], [payment_order.pay_to_address])
        self.assertEqual(str(kwargs['amount']), '3.25000000')
        payment_order.refresh_from_db()
        product_order.refresh_from_db()
        self.assertEqual(payment_order.txid, 'tx-product-wallet-001')
        self.assertEqual(payment_order.status, PaymentOrder.STATUS_PENDING)
        self.assertEqual(product_order.status, ProductOrder.STATUS_PENDING_PAYMENT)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()
        mock_tx_show.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_non_buyer_cannot_pay_another_users_product_order(self, mock_unlock, mock_send, mock_lock):
        owner = self.create_user('wallet-product-owner@example.com')
        owner.linked_wallet_id = 'wallet-main'
        owner.save(update_fields=['linked_wallet_id'])
        attacker = self.create_user('wallet-product-attacker@example.com')
        attacker.linked_wallet_id = 'wallet-main'
        attacker.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-2')
        shipping = self.create_shipping_address(owner)
        product_order, _ = self.create_product_order(owner, product, shipping)

        self.client.force_authenticate(user=attacker)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_payment_missing_pay_to_address_returns_validation_error(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-noaddr@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-3')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.pay_to_address = ''
        payment_order.save(update_fields=['pay_to_address', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('missing pay_to_address', response.data['detail'])
        mock_unlock.assert_not_called()
        mock_send.assert_not_called()
        mock_lock.assert_not_called()

    @patch('apps.accounts.views.WalletPrototypePayOrderService.pay_payment_order')
    def test_product_endpoint_uses_shared_pay_payment_order_method(self, mock_pay_payment_order):
        buyer = self.create_user('shared-product-buyer@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-shared-product-store')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('2.50000000')
        payment_order.save(update_fields=['expected_amount_lbc', 'updated_at'])
        mock_pay_payment_order.return_value = {
            'order_no': payment_order.order_no,
            'txid': 'tx-shared-product',
            'wallet_relocked': True,
        }

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['txid'], 'tx-shared-product')
        kwargs = mock_pay_payment_order.call_args.kwargs
        self.assertEqual(kwargs['amount_override'], Decimal('2.50000000'))
        self.assertEqual(kwargs['order'], payment_order)

    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_locked_wallet_error_returns_clear_detail(self, mock_unlock, mock_send):
        buyer = self.create_user('product-locked-wallet@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-locked-wallet-store')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_unlock.return_value = True
        mock_send.side_effect = LbryDaemonError('Cannot spend funds with locked wallet, unlock first.')

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn('locked wallet', response.data['detail'])

    def test_product_wallet_payment_missing_linked_wallet_returns_400(self):
        buyer = self.create_user('wallet-product-nowallet@example.com')
        _, _, product = self.create_store_product(slug='wallet-product-store-4')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data['detail'], 'Missing linked wallet.')

    def test_product_wallet_payment_missing_password_validation_error(self):
        buyer = self.create_user('wallet-product-nopassword@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-5')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('password', response.data)

    def test_product_wallet_payment_non_pending_order_returns_409(self):
        buyer = self.create_user('wallet-product-nonpending@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-7')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        product_order.status = ProductOrder.STATUS_PAID
        product_order.save(update_fields=['status', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)

    def test_product_wallet_payment_missing_expected_amount_returns_validation_error(self):
        buyer = self.create_user('wallet-product-noexpected@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-noexpected')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = None
        payment_order.save(update_fields=['expected_amount_lbc', 'updated_at'])

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('missing expected_amount_lbc', response.data['detail'])

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_duplicate_product_payment_does_not_trigger_second_wallet_send(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-duplicate@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-duplicate')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_unlock.return_value = True
        mock_send.return_value = {'txid': 'tx-product-duplicate-001'}

        self.client.force_authenticate(user=buyer)
        first = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(first.status_code, status.HTTP_200_OK)

        second = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(second.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(second.data['txid'], 'tx-product-duplicate-001')
        self.assertEqual(mock_send.call_count, 1)

    def test_get_product_wallet_send_amount_prefers_expected_amount_field(self):
        buyer = self.create_user('helper-amount-buyer@example.com')
        _, _, product = self.create_store_product(slug='wallet-helper-store')
        shipping = self.create_shipping_address(buyer)
        product_order, payment_order = self.create_product_order(buyer, product, shipping)
        payment_order.expected_amount_lbc = Decimal('7.77000000')
        payment_order.amount = Decimal('99.50')
        payment_order.save(update_fields=['expected_amount_lbc', 'amount', 'updated_at'])

        amount = get_product_wallet_send_amount(payment_order=payment_order, product_order=product_order)
        self.assertEqual(amount, Decimal('7.77000000'))

    @patch('apps.accounts.services.LbryDaemonClient.wallet_lock')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    @patch('apps.accounts.services.LbryDaemonClient.wallet_unlock')
    def test_product_wallet_lock_attempted_after_send_failure(self, mock_unlock, mock_send, mock_lock):
        buyer = self.create_user('wallet-product-sendfail@example.com')
        buyer.linked_wallet_id = 'wallet-main'
        buyer.save(update_fields=['linked_wallet_id'])
        _, _, product = self.create_store_product(slug='wallet-product-store-6')
        shipping = self.create_shipping_address(buyer)
        product_order, _ = self.create_product_order(buyer, product, shipping)
        mock_unlock.return_value = True
        mock_send.side_effect = LbryDaemonError('send failed')

        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('wallet-prototype-pay-product-order'),
            {'order_no': product_order.order_no, 'wallet_id': 'wallet-main', 'password': 'temporary-secret'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        mock_unlock.assert_called_once()
        mock_send.assert_called_once()
        mock_lock.assert_called_once()

    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    def test_verify_now_endpoint_updates_order_when_confirmed(self, mock_tx_show):
        user = self.create_user('verify-now@example.com')
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan)
        order.txid = 'tx-verify-now'
        order.save(update_fields=['txid', 'updated_at'])
        mock_tx_show.return_value = {
            'txid': 'tx-verify-now',
            'confirmations': 2,
            'outputs': [{'nout': 0, 'address': order.pay_to_address, 'amount': '30.0'}],
        }

        self.client.force_authenticate(user=user)
        response = self.client.post(reverse('membership-order-verify-now', args=[order.order_no]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.STATUS_PAID)
        self.assertTrue(response.data['verification']['paid'])

    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    def test_verify_now_keeps_pending_when_confirmations_low(self, mock_tx_show):
        user = self.create_user('verify-pending@example.com')
        plan = self.create_plan()
        order = self.create_order(user=user, plan=plan)
        order.txid = 'tx-verify-pending'
        order.save(update_fields=['txid', 'updated_at'])
        mock_tx_show.return_value = {
            'txid': 'tx-verify-pending',
            'confirmations': 0,
            'outputs': [{'nout': 0, 'address': order.pay_to_address, 'amount': '30.0'}],
        }

        self.client.force_authenticate(user=user)
        response = self.client.post(reverse('membership-order-verify-now', args=[order.order_no]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.STATUS_PENDING)
        self.assertFalse(response.data['verification']['paid'])


@override_settings(
    LBRY_DAEMON_URL='http://127.0.0.1:5279',
    LBC_MIN_CONFIRMATIONS=2,
    LBC_TX_PAGE_SIZE=50,
)
class MembershipPaymentDetectionServiceTestCase(APITestCase):
    class FakeDaemonClient:
        def __init__(self, tx_list=None, tx_show_map=None):
            self.tx_list = tx_list or []
            self.tx_show_map = tx_show_map or {}

        def transaction_list(self, wallet_id=None, page=None, page_size=None):
            return self.tx_list

        def transaction_show(self, txid):
            return self.tx_show_map[txid]

    def create_user(self, email='detect@example.com'):
        return User.objects.create_user(email=email, password='strong-pass-123', first_name='Detect', last_name='User')

    def create_plan(self, code=None, duration_days=30, price='10.00000000'):
        if code is None:
            code = f'monthly-{MembershipPlan.objects.count() + 1}'
        return MembershipPlan.objects.create(
            code=code,
            name=f'Plan {code}',
            description='Plan',
            price_lbc=price,
            duration_days=duration_days,
            is_active=True,
            sort_order=1,
        )

    def create_order(self, *, user, plan, address, status=PaymentOrder.STATUS_PENDING):
        order = PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            target_type='membership_plan',
            target_id=plan.id,
            plan_code_snapshot=plan.code,
            plan_name_snapshot=plan.name,
            expected_amount_lbc=plan.price_lbc,
            amount='0.00',
            currency='LBC',
            status=status,
            order_no=f'MO-{address[-6:]}',
            pay_to_address=address,
        )
        wallet = WalletAddress.objects.create(
            address=address,
            usage_type=WalletAddress.USAGE_MEMBERSHIP,
            status=WalletAddress.STATUS_ASSIGNED,
            assigned_order=order,
            wallet_id='wallet-main',
        )
        order.wallet_address = wallet
        order.save(update_fields=['wallet_address', 'updated_at'])
        return order

    def run_sync(self, txid, tx_payload):
        daemon = self.FakeDaemonClient(
            tx_list=[{'txid': txid}],
            tx_show_map={txid: tx_payload},
        )
        service = PaymentDetectionService(daemon_client=daemon)
        return service.sync_membership_orders()

    def test_exact_payment_marks_order_paid(self):
        user = self.create_user('exact@example.com')
        plan = self.create_plan(price='10.00000000')
        order = self.create_order(user=user, plan=plan, address='bExactAddress001')

        self.run_sync(
            'tx-exact',
            {
                'txid': 'tx-exact',
                'confirmations': 2,
                'height': 321,
                'outputs': [
                    {'nout': 0, 'address': 'bExactAddress001', 'amount': '10.0'},
                ],
            },
        )
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.STATUS_PAID)
        self.assertEqual(order.txid, 'tx-exact')
        self.assertEqual(str(order.actual_amount_lbc), '10.00000000')
        self.assertEqual(order.confirmations, 2)
        self.assertIsNotNone(order.paid_at)
        self.assertTrue(UserMembership.objects.filter(source_order=order).exists())

    def test_overpayment_marks_order_overpaid_and_activates(self):
        user = self.create_user('overpay@example.com')
        plan = self.create_plan(code=MembershipPlan.CODE_QUARTERLY, duration_days=90, price='10.00000000')
        order = self.create_order(user=user, plan=plan, address='bOverAddress001')

        self.run_sync(
            'tx-over',
            {
                'txid': 'tx-over',
                'confirmations': 3,
                'outputs': [{'nout': 1, 'address': 'bOverAddress001', 'amount': '12.5'}],
            },
        )
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.STATUS_OVERPAID)
        self.assertTrue(UserMembership.objects.filter(source_order=order).exists())

    def test_underpayment_does_not_mark_paid(self):
        user = self.create_user('underpay@example.com')
        plan = self.create_plan(price='10.00000000')
        order = self.create_order(user=user, plan=plan, address='bUnderAddress001')

        self.run_sync(
            'tx-under',
            {
                'txid': 'tx-under',
                'confirmations': 5,
                'outputs': [{'nout': 0, 'address': 'bUnderAddress001', 'amount': '9.0'}],
            },
        )
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.STATUS_UNDERPAID)
        self.assertFalse(UserMembership.objects.filter(source_order=order).exists())

    def test_duplicate_polling_is_idempotent(self):
        user = self.create_user('dupe@example.com')
        plan = self.create_plan(price='10.00000000')
        order = self.create_order(user=user, plan=plan, address='bDupeAddress001')
        tx_payload = {
            'txid': 'tx-dupe',
            'confirmations': 3,
            'outputs': [{'nout': 0, 'address': 'bDupeAddress001', 'amount': '10.0'}],
        }

        self.run_sync('tx-dupe', tx_payload)
        self.run_sync('tx-dupe', tx_payload)
        self.assertEqual(ChainReceipt.objects.filter(txid='tx-dupe', vout=0).count(), 1)
        self.assertEqual(OrderPayment.objects.filter(order=order).count(), 1)
        self.assertEqual(UserMembership.objects.filter(source_order=order).count(), 1)

    def test_active_membership_extension_starts_from_current_end(self):
        user = self.create_user('extend@example.com')
        plan = self.create_plan(price='10.00000000', duration_days=30)
        existing_order = self.create_order(user=user, plan=plan, address='bExisting0001')
        existing_order.status = PaymentOrder.STATUS_PAID
        existing_order.paid_at = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        existing_order.save(update_fields=['status', 'paid_at', 'updated_at'])
        current_start = datetime.now(timezone.utc) - timedelta(days=1)
        current_end = datetime.now(timezone.utc) + timedelta(days=15)
        existing_membership = UserMembership.objects.create(
            user=user,
            source_order=existing_order,
            plan=plan,
            status=UserMembership.STATUS_ACTIVE,
            starts_at=current_start,
            ends_at=current_end,
        )
        order = self.create_order(user=user, plan=plan, address='bExtendAddress001')

        self.run_sync(
            'tx-extend',
            {
                'txid': 'tx-extend',
                'confirmations': 2,
                'outputs': [{'nout': 0, 'address': 'bExtendAddress001', 'amount': '10.0'}],
            },
        )
        new_membership = UserMembership.objects.get(source_order=order)
        self.assertEqual(new_membership.starts_at, existing_membership.ends_at)

    def test_expired_order_late_payment_is_marked_paid_with_note(self):
        user = self.create_user('expired@example.com')
        plan = self.create_plan(price='10.00000000')
        order = self.create_order(user=user, plan=plan, address='bExpiredAddress01', status=PaymentOrder.STATUS_EXPIRED)

        self.run_sync(
            'tx-expired',
            {
                'txid': 'tx-expired',
                'confirmations': 2,
                'outputs': [{'nout': 0, 'address': 'bExpiredAddress01', 'amount': '10.0'}],
            },
        )
        order.refresh_from_db()
        self.assertEqual(order.status, PaymentOrder.STATUS_PAID)
        self.assertIn('paid_after_expiry', order.paid_note)

    def test_receipt_persistence_stores_output_details_and_raw_payload(self):
        user = self.create_user('receipt@example.com')
        plan = self.create_plan(price='10.00000000')
        order = self.create_order(user=user, plan=plan, address='bReceiptAddress01')
        payload = {
            'txid': 'tx-receipt',
            'wallet_id': 'wallet-main',
            'confirmations': 2,
            'height': 777,
            'outputs': [{'nout': 4, 'address': 'bReceiptAddress01', 'amount': '10.0'}],
        }

        self.run_sync('tx-receipt', payload)
        receipt = ChainReceipt.objects.get(txid='tx-receipt', vout=4)
        self.assertEqual(receipt.wallet_id, 'wallet-main')
        self.assertEqual(receipt.address, 'bReceiptAddress01')
        self.assertEqual(str(receipt.amount_lbc), '10.00000000')
        self.assertEqual(receipt.block_height, 777)
        self.assertEqual(receipt.matched_order_id, order.id)
        self.assertEqual(receipt.raw_payload['txid'], 'tx-receipt')

    def test_membership_activation_service_is_idempotent(self):
        user = self.create_user('activation@example.com')
        plan = self.create_plan(price='10.00000000')
        order = self.create_order(user=user, plan=plan, address='bActivateAddress')
        order.status = PaymentOrder.STATUS_PAID
        order.paid_at = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
        order.save(update_fields=['status', 'paid_at', 'updated_at'])

        activation_service = MembershipActivationService()
        first = activation_service.activate_for_order(order=order)
        second = activation_service.activate_for_order(order=order)
        self.assertEqual(first.id, second.id)
        self.assertEqual(UserMembership.objects.filter(source_order=order).count(), 1)

    def test_detection_uses_txid_hint_when_platform_address_is_shared(self):
        user = self.create_user('shared-hint@example.com')
        plan = self.create_plan(price='10.00000000')
        shared_address = 'bSharedPlatformAddress'
        order_1 = PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            target_type='membership_plan',
            target_id=plan.id,
            plan_code_snapshot=plan.code,
            plan_name_snapshot=plan.name,
            expected_amount_lbc=plan.price_lbc,
            amount='0.00',
            currency='LBC',
            status=PaymentOrder.STATUS_PENDING,
            order_no='MOSHARED001',
            pay_to_address=shared_address,
        )
        order_2 = PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            target_type='membership_plan',
            target_id=plan.id,
            plan_code_snapshot=plan.code,
            plan_name_snapshot=plan.name,
            expected_amount_lbc=plan.price_lbc,
            amount='0.00',
            currency='LBC',
            status=PaymentOrder.STATUS_PENDING,
            order_no='MOSHARED002',
            pay_to_address=shared_address,
        )
        order_2.txid = 'tx-shared-target'
        order_2.save(update_fields=['txid', 'updated_at'])

        self.run_sync(
            'tx-shared-target',
            {
                'txid': 'tx-shared-target',
                'confirmations': 3,
                'outputs': [{'nout': 0, 'address': shared_address, 'amount': '10.0'}],
            },
        )
        order_1.refresh_from_db()
        order_2.refresh_from_db()
        self.assertEqual(order_1.status, PaymentOrder.STATUS_PENDING)
        self.assertEqual(order_2.status, PaymentOrder.STATUS_PAID)


@override_settings(
    PRODUCT_ORDER_EXPIRE_MINUTES=30,
    PRODUCT_PLATFORM_RECEIVE_ADDRESS='bProductPlatformAddress001',
    LBRY_DAEMON_URL='http://127.0.0.1:5279',
)
class ProductOrderFlowAPITestCase(APITestCase):
    def create_user(self, email='buyer@example.com', **extra):
        defaults = {'first_name': 'Flow', 'last_name': 'User'}
        defaults.update(extra)
        return User.objects.create_user(email=email, password='strong-pass-123', **defaults)

    def create_store_product(self, owner_email='seller@example.com', slug='seller-store'):
        seller = self.create_user(owner_email)
        store = SellerStore.objects.create(owner=seller, name='Seller Store', slug=slug, is_active=True)
        product = Product.objects.create(
            store=store,
            title='Thai Product',
            slug=f'product-{store.id}',
            price_amount='99.50',
            price_currency='USD',
            stock_quantity=10,
            status=Product.STATUS_ACTIVE,
        )
        return seller, store, product

    def create_shipping_address(self, buyer):
        return UserShippingAddress.objects.create(
            user=buyer,
            receiver_name='Buyer Receiver',
            phone='0800000000',
            country='Thailand',
            province='Bangkok',
            city='Bangkok',
            district='Pathum Wan',
            street_address='123 Main',
            postal_code='10330',
            is_default=True,
        )

    def create_product_order(self, buyer, product, shipping_address):
        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('product-order-list-create'),
            {'product_id': product.id, 'quantity': 1, 'shipping_address_id': shipping_address.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return ProductOrder.objects.get(order_no=response.data['order_no']), response

    def test_shipping_address_crud(self):
        buyer = self.create_user('shipping@example.com')
        self.client.force_authenticate(user=buyer)
        create_response = self.client.post(
            reverse('account-shipping-address-list-create'),
            {
                'receiver_name': 'John Doe',
                'phone': '0811111111',
                'country': 'Thailand',
                'province': 'Bangkok',
                'city': 'Bangkok',
                'district': 'Sathon',
                'street_address': 'Road 123',
                'postal_code': '10120',
                'is_default': True,
            },
            format='json',
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        address_id = create_response.data['id']

        list_response = self.client.get(reverse('account-shipping-address-list-create'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)

        patch_response = self.client.patch(
            reverse('account-shipping-address-detail', args=[address_id]),
            {'city': 'Nonthaburi'},
            format='json',
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_response.data['city'], 'Nonthaburi')

        delete_response = self.client.delete(reverse('account-shipping-address-detail', args=[address_id]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(UserShippingAddress.objects.filter(user=buyer).count(), 0)

    def test_create_product_order_requires_shipping_address(self):
        buyer = self.create_user('no-address@example.com')
        _, _, product = self.create_store_product(slug='store-no-address')
        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('product-order-list-create'),
            {'product_id': product.id, 'quantity': 1},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('shipping_address_id', response.data)

    def test_create_product_order_success_and_qr_fields(self):
        buyer = self.create_user('order-ok@example.com')
        _, _, product = self.create_store_product(slug='store-order-ok')
        address = self.create_shipping_address(buyer)
        order, response = self.create_product_order(buyer, product, address)
        self.assertEqual(order.status, ProductOrder.STATUS_PENDING_PAYMENT)
        self.assertIsNotNone(order.payment_order_id)
        self.assertEqual(order.payment_order.currency, 'THB-LTT')
        self.assertEqual(order.payment_order.order_type, PaymentOrder.TYPE_PRODUCT)
        self.assertEqual(order.payment_order.target_type, 'product_order')
        self.assertEqual(response.data['currency'], 'THB-LTT')
        self.assertTrue(response.data['qr_payload'])
        self.assertTrue(response.data['qr_text'])
        self.assertTrue(response.data['payment_uri'])

    def test_product_order_creation_uses_configured_product_receive_address(self):
        buyer = self.create_user('configured-address-buyer@example.com')
        _, _, product = self.create_store_product(slug='store-configured-address')
        address = self.create_shipping_address(buyer)
        _, response = self.create_product_order(buyer, product, address)
        self.assertEqual(response.data['pay_to_address'], 'bProductPlatformAddress001')
        self.assertEqual(response.data['qr_payload']['pay_to_address'], 'bProductPlatformAddress001')

    @override_settings(
        PRODUCT_PLATFORM_RECEIVE_ADDRESS='',
        LBRY_PLATFORM_RECEIVE_ADDRESS='',
        LBRY_PLATFORM_WALLET_ID='ltt-admin-stream',
    )
    @patch('apps.accounts.services.LbryDaemonClient.address_unused')
    def test_product_order_creation_without_fixed_address_calls_daemon(self, mock_address_unused):
        mock_address_unused.return_value = {
            'address': 'bDynamicProductAddress001',
            'wallet_id': 'ltt-admin-stream',
            'account_id': 'account-main',
        }
        buyer = self.create_user('dynamic-address-buyer@example.com')
        _, _, product = self.create_store_product(slug='store-dynamic-address')
        address = self.create_shipping_address(buyer)
        order, response = self.create_product_order(buyer, product, address)
        mock_address_unused.assert_called_once_with(wallet_id='ltt-admin-stream', account_id=None)
        self.assertEqual(order.payment_order.pay_to_address, 'bDynamicProductAddress001')
        self.assertEqual(response.data['pay_to_address'], 'bDynamicProductAddress001')
        self.assertEqual(response.data['qr_payload']['pay_to_address'], 'bDynamicProductAddress001')
        self.assertIn('bDynamicProductAddress001', response.data['payment_uri'])

    @override_settings(
        PRODUCT_PLATFORM_RECEIVE_ADDRESS='',
        LBRY_PLATFORM_RECEIVE_ADDRESS='',
        LBRY_PLATFORM_WALLET_ID='ltt-admin-stream',
    )
    @patch('apps.accounts.services.LbryDaemonClient.address_unused')
    def test_product_order_creation_daemon_failure_returns_503(self, mock_address_unused):
        mock_address_unused.side_effect = LbryDaemonError('daemon unavailable')
        buyer = self.create_user('dynamic-address-fail@example.com')
        _, _, product = self.create_store_product(slug='store-dynamic-fail')
        address = self.create_shipping_address(buyer)
        self.client.force_authenticate(user=buyer)
        response = self.client.post(
            reverse('product-order-list-create'),
            {'product_id': product.id, 'quantity': 1, 'shipping_address_id': address.id},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data['detail'], 'Unable to allocate product payment address from platform wallet.')

    def test_qr_payload_token_standard_and_signature(self):
        buyer = self.create_user('qr-standard@example.com')
        _, _, product = self.create_store_product(slug='store-qr-standard')
        address = self.create_shipping_address(buyer)
        _, response = self.create_product_order(buyer, product, address)
        payload = response.data['qr_payload']
        self.assertEqual(payload['blockchain'], 'LTT')
        self.assertEqual(payload['token_name'], 'LTT Thai Baht Stablecoin')
        self.assertEqual(payload['token_symbol'], 'THB-LTT')
        self.assertEqual(payload['peg'], '1 THB-LTT = 1 THB')
        self.assertTrue(verify_product_qr_signature(payload))

    def test_qr_signature_tampering_fails(self):
        buyer = self.create_user('qr-tamper@example.com')
        _, _, product = self.create_store_product(slug='store-qr-tamper')
        address = self.create_shipping_address(buyer)
        _, response = self.create_product_order(buyer, product, address)
        payload = response.data['qr_payload']
        tampered_amount = dict(payload)
        tampered_amount['expected_amount'] = '999.99'
        self.assertFalse(verify_product_qr_signature(tampered_amount))
        tampered_address = dict(payload)
        tampered_address['pay_to_address'] = 'bTampered'
        self.assertFalse(verify_product_qr_signature(tampered_address))
        tampered_order = dict(payload)
        tampered_order['order_no'] = 'PO-TAMPER'
        self.assertFalse(verify_product_qr_signature(tampered_order))

    def test_admin_mark_paid_updates_product_and_payment_order(self):
        admin = self.create_user('admin-paid@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('buyer-paid@example.com')
        _, _, product = self.create_store_product(slug='store-paid')
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)

        self.client.force_authenticate(user=admin)
        response = self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        order.payment_order.refresh_from_db()
        self.assertEqual(order.status, ProductOrder.STATUS_PAID)
        self.assertEqual(order.payment_order.status, PaymentOrder.STATUS_PAID)
        self.assertIsNotNone(order.paid_at)

    def test_seller_can_ship_only_own_paid_orders(self):
        admin = self.create_user('admin-ship@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('buyer-ship@example.com')
        seller, _, product = self.create_store_product('seller-own@example.com', slug='store-own-ship')
        other_seller = self.create_user('seller-other@example.com')
        SellerStore.objects.create(owner=other_seller, name='Other', slug='store-other-ship', is_active=True)
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        self.client.force_authenticate(user=admin)
        self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')

        self.client.force_authenticate(user=other_seller)
        forbidden = self.client.post(
            reverse('seller-product-order-ship', args=[order.order_no]),
            {'carrier': 'Thailand Post', 'tracking_number': 'TH1'},
            format='json',
        )
        self.assertEqual(forbidden.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=seller)
        ok = self.client.post(
            reverse('seller-product-order-ship', args=[order.order_no]),
            {'carrier': 'Thailand Post', 'tracking_number': 'TH123456789', 'tracking_url': 'https://example.com/t', 'shipped_note': 'packed'},
            format='json',
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, ProductOrder.STATUS_SHIPPING)
        self.assertTrue(ProductShipment.objects.filter(product_order=order).exists())

    def test_buyer_confirm_received_only_own_shipping_order_and_creates_payout(self):
        admin = self.create_user('admin-receive@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('buyer-receive@example.com')
        other_buyer = self.create_user('other-buyer@example.com')
        seller, _, product = self.create_store_product('seller-receive@example.com', slug='store-receive')
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)

        self.client.force_authenticate(user=admin)
        self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')
        self.client.force_authenticate(user=seller)
        self.client.post(
            reverse('seller-product-order-ship', args=[order.order_no]),
            {'carrier': 'Thailand Post', 'tracking_number': 'TH2'},
            format='json',
        )

        self.client.force_authenticate(user=other_buyer)
        forbidden = self.client.post(reverse('product-order-confirm-received', args=[order.order_no]), format='json')
        self.assertEqual(forbidden.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=buyer)
        ok = self.client.post(reverse('product-order-confirm-received', args=[order.order_no]), format='json')
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, ProductOrder.STATUS_COMPLETED)
        payout = SellerPayout.objects.get(product_order=order)
        self.assertEqual(payout.status, SellerPayout.STATUS_PENDING)

    def test_admin_mark_settled_updates_payout_and_order(self):
        admin = self.create_user('admin-settle@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('buyer-settle@example.com')
        seller, _, product = self.create_store_product('seller-settle@example.com', slug='store-settle')
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)

        self.client.force_authenticate(user=admin)
        self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')
        self.client.force_authenticate(user=seller)
        self.client.post(
            reverse('seller-product-order-ship', args=[order.order_no]),
            {'carrier': 'Thailand Post', 'tracking_number': 'TH3'},
            format='json',
        )
        self.client.force_authenticate(user=buyer)
        self.client.post(reverse('product-order-confirm-received', args=[order.order_no]), format='json')

        self.client.force_authenticate(user=admin)
        response = self.client.post(
            reverse('admin-product-order-mark-settled', args=[order.order_no]),
            {'txid': 'settle-tx-1', 'payout_address': 'seller-address-1', 'note': 'manual settlement'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        payout = SellerPayout.objects.get(product_order=order)
        self.assertEqual(order.status, ProductOrder.STATUS_SETTLED)
        self.assertEqual(payout.status, SellerPayout.STATUS_PAID)
        self.assertEqual(payout.txid, 'settle-tx-1')

    def test_seller_order_list_and_detail_permissions(self):
        buyer = self.create_user('seller-list-buyer@example.com')
        seller, _, product = self.create_store_product('seller-list-owner@example.com', slug='store-seller-list')
        other_seller, _, _ = self.create_store_product('seller-list-other@example.com', slug='store-seller-list-other')
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)

        self.client.force_authenticate(user=seller)
        list_response = self.client.get(reverse('seller-product-order-list'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]['order_no'], order.order_no)
        detail_response = self.client.get(reverse('seller-product-order-detail', args=[order.order_no]))
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.data['order_no'], order.order_no)

        self.client.force_authenticate(user=other_seller)
        forbidden = self.client.get(reverse('seller-product-order-detail', args=[order.order_no]))
        self.assertEqual(forbidden.status_code, status.HTTP_404_NOT_FOUND)

    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    def test_product_txid_hint_verifies_without_membership_activation(self, mock_show):
        buyer = self.create_user('txhint-product-buyer@example.com')
        _, _, product = self.create_store_product('txhint-product-seller@example.com', slug='store-txhint-product')
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        mock_show.return_value = {
            'txid': 'tx-product-hint',
            'confirmations': 2,
            'outputs': [{'nout': 0, 'address': order.payment_order.pay_to_address, 'amount': str(order.total_amount)}],
        }
        with patch.object(MembershipActivationService, 'activate_for_order') as mock_activation:
            self.client.force_authenticate(user=buyer)
            response = self.client.post(
                reverse('product-order-tx-hint', args=[order.order_no]),
                {'txid': 'tx-product-hint'},
                format='json',
            )
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertTrue(response.data['verified'])
            mock_activation.assert_not_called()

    @override_settings(LBC_MIN_CONFIRMATIONS=2, LBC_TX_PAGE_SIZE=50)
    @patch('apps.accounts.services.LbryDaemonClient.transaction_list')
    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    def test_product_payment_sync_paid_underpaid_overpaid(self, mock_show, mock_list):
        buyer = self.create_user('sync-buyer@example.com')
        _, _, product = self.create_store_product('sync-seller@example.com', slug='store-sync')
        address = self.create_shipping_address(buyer)
        paid_order, _ = self.create_product_order(buyer, product, address)
        under_order, _ = self.create_product_order(buyer, product, address)
        over_order, _ = self.create_product_order(buyer, product, address)
        paid_order.payment_order.pay_to_address = 'bPaidAddressSync'
        paid_order.payment_order.save(update_fields=['pay_to_address', 'updated_at'])
        under_order.payment_order.pay_to_address = 'bUnderAddressSync'
        under_order.payment_order.save(update_fields=['pay_to_address', 'updated_at'])
        over_order.payment_order.pay_to_address = 'bOverAddressSync'
        over_order.payment_order.save(update_fields=['pay_to_address', 'updated_at'])

        mock_list.return_value = [{'txid': 'tx-paid'}, {'txid': 'tx-under'}, {'txid': 'tx-over'}]
        show_map = {
            'tx-paid': {'txid': 'tx-paid', 'confirmations': 3, 'outputs': [{'nout': 0, 'address': 'bPaidAddressSync', 'amount': str(paid_order.total_amount)}]},
            'tx-under': {'txid': 'tx-under', 'confirmations': 3, 'outputs': [{'nout': 0, 'address': 'bUnderAddressSync', 'amount': '1.00'}]},
            'tx-over': {'txid': 'tx-over', 'confirmations': 3, 'outputs': [{'nout': 0, 'address': 'bOverAddressSync', 'amount': str(over_order.total_amount + 1)}]},
        }
        mock_show.side_effect = lambda txid: show_map[txid]

        result = ProductPaymentDetectionService().sync_product_orders()
        paid_order.refresh_from_db()
        under_order.refresh_from_db()
        over_order.refresh_from_db()
        self.assertGreaterEqual(result['matched_receipts'], 3)
        self.assertEqual(paid_order.status, ProductOrder.STATUS_PAID)
        self.assertEqual(under_order.status, ProductOrder.STATUS_PENDING_PAYMENT)
        self.assertEqual(under_order.payment_order.status, PaymentOrder.STATUS_UNDERPAID)
        self.assertEqual(over_order.status, ProductOrder.STATUS_PAID)
        self.assertEqual(over_order.payment_order.status, PaymentOrder.STATUS_OVERPAID)

    def test_stock_lock_and_release_timeout_idempotent(self):
        buyer = self.create_user('stock-timeout-buyer@example.com')
        _, _, product = self.create_store_product('stock-timeout-seller@example.com', slug='store-stock-timeout')
        initial_stock = product.stock_quantity
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, initial_stock - 1)

        order.expires_at = django_timezone.now() - timedelta(minutes=1)
        order.save(update_fields=['expires_at', 'updated_at'])
        result1 = ProductOrderService().release_expired_pending_orders()
        result2 = ProductOrderService().release_expired_pending_orders()
        order.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(order.status, ProductOrder.STATUS_CANCELLED)
        self.assertEqual(order.cancel_reason, 'payment_timeout')
        self.assertEqual(product.stock_quantity, initial_stock)
        self.assertGreaterEqual(result1['released_orders'], 1)
        self.assertEqual(result2['released_orders'], 0)

    def test_paid_product_order_expiry_does_not_release_stock(self):
        admin = self.create_user('stock-paid-admin@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('stock-paid-buyer@example.com')
        _, _, product = self.create_store_product('stock-paid-seller@example.com', slug='store-stock-paid')
        initial_stock = product.stock_quantity
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        self.client.force_authenticate(user=admin)
        self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')
        order.refresh_from_db()
        order.expires_at = django_timezone.now() - timedelta(minutes=1)
        order.save(update_fields=['expires_at', 'updated_at'])
        ProductOrderService().release_expired_pending_orders()
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, initial_stock - 1)

    @patch('apps.accounts.services.LbryDaemonClient.transaction_show')
    @patch('apps.accounts.services.LbryDaemonClient.transaction_list')
    def test_sync_product_payments_command_prints_summary(self, mock_list, mock_show):
        buyer = self.create_user('cmd-sync-buyer@example.com')
        _, _, product = self.create_store_product('cmd-sync-seller@example.com', slug='store-cmd-sync')
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        mock_list.return_value = [{'txid': 'tx-cmd-sync'}]
        mock_show.return_value = {
            'txid': 'tx-cmd-sync',
            'confirmations': 2,
            'outputs': [{'nout': 0, 'address': order.payment_order.pay_to_address, 'amount': str(order.total_amount)}],
        }
        out = StringIO()
        management.call_command('sync_product_payments', stdout=out)
        rendered = out.getvalue()
        self.assertIn('scanned_orders=', rendered)
        self.assertIn('matched_receipts=', rendered)
        self.assertIn('paid_orders=', rendered)
        self.assertIn('underpaid_orders=', rendered)
        self.assertIn('overpaid_orders=', rendered)

    def test_release_expired_product_orders_command_prints_summary(self):
        buyer = self.create_user('cmd-release-buyer@example.com')
        _, _, product = self.create_store_product('cmd-release-seller@example.com', slug='store-cmd-release')
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        order.expires_at = django_timezone.now() - timedelta(minutes=1)
        order.save(update_fields=['expires_at', 'updated_at'])
        out = StringIO()
        management.call_command('release_expired_product_orders', stdout=out)
        rendered = out.getvalue()
        self.assertIn('scanned_orders=', rendered)
        self.assertIn('released_orders=', rendered)
        self.assertIn('restored_stock_quantity=', rendered)

    def test_seller_payout_address_crud_and_default_rules(self):
        seller, store, _ = self.create_store_product('payout-seller@example.com', slug='store-payout-address')
        self.client.force_authenticate(user=seller)
        first = self.client.post(
            reverse('seller-payout-address-list-create'),
            {'address': 'bPayoutAddr1', 'label': 'main'},
            format='json',
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertTrue(first.data['is_default'])

        second = self.client.post(
            reverse('seller-payout-address-list-create'),
            {'address': 'bPayoutAddr2', 'label': 'backup', 'is_default': True},
            format='json',
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)
        first_obj = SellerPayoutAddress.objects.get(id=first.data['id'])
        second_obj = SellerPayoutAddress.objects.get(id=second.data['id'])
        self.assertFalse(first_obj.is_default)
        self.assertTrue(second_obj.is_default)

        delete_response = self.client.delete(reverse('seller-payout-address-detail', args=[second_obj.id]))
        self.assertEqual(delete_response.status_code, status.HTTP_204_NO_CONTENT)
        second_obj.refresh_from_db()
        self.assertFalse(second_obj.is_active)

        other_seller, _, _ = self.create_store_product('payout-other@example.com', slug='store-payout-other')
        self.client.force_authenticate(user=other_seller)
        forbidden = self.client.patch(
            reverse('seller-payout-address-detail', args=[first_obj.id]),
            {'label': 'hacked'},
            format='json',
        )
        self.assertEqual(forbidden.status_code, status.HTTP_404_NOT_FOUND)

    @override_settings(PRODUCT_AUTO_PAYOUT_ENABLED=False)
    def test_auto_payout_disabled_does_nothing(self):
        result = ProductPayoutService().settle_pending_payouts()
        self.assertEqual(result['scanned_payouts'], 0)
        self.assertEqual(result['settled_payouts'], 0)

    @override_settings(
        PRODUCT_AUTO_PAYOUT_ENABLED=True,
        PRODUCT_PAYOUT_WALLET_ID='wallet-main',
        PRODUCT_PAYOUT_ACCOUNT_ID='account-main',
        PRODUCT_PAYOUT_MIN_DELAY_HOURS=0,
    )
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    def test_auto_payout_settles_and_is_idempotent(self, mock_send):
        admin = self.create_user('payout-admin@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('payout-buyer@example.com')
        seller, store, product = self.create_store_product('payout-owner@example.com', slug='store-payout-service')
        SellerPayoutAddress.objects.create(
            seller_store=store,
            address='bSellerPayoutAddress001',
            is_default=True,
            is_active=True,
        )
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        self.client.force_authenticate(user=admin)
        self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')
        self.client.force_authenticate(user=seller)
        self.client.post(
            reverse('seller-product-order-ship', args=[order.order_no]),
            {'carrier': 'TH', 'tracking_number': 'TN-1'},
            format='json',
        )
        self.client.force_authenticate(user=buyer)
        self.client.post(reverse('product-order-confirm-received', args=[order.order_no]), format='json')
        mock_send.return_value = {'txid': 'tx-payout-001'}

        first = ProductPayoutService().settle_pending_payouts()
        order.refresh_from_db()
        payout = SellerPayout.objects.get(product_order=order)
        self.assertEqual(first['settled_payouts'], 1)
        self.assertEqual(order.status, ProductOrder.STATUS_SETTLED)
        self.assertEqual(payout.status, SellerPayout.STATUS_PAID)
        self.assertEqual(payout.txid, 'tx-payout-001')
        self.assertEqual(payout.payout_address, 'bSellerPayoutAddress001')

        second = ProductPayoutService().settle_pending_payouts()
        self.assertEqual(second['settled_payouts'], 0)

    @override_settings(
        PRODUCT_AUTO_PAYOUT_ENABLED=True,
        PRODUCT_PAYOUT_WALLET_ID='wallet-main',
        PRODUCT_PAYOUT_ACCOUNT_ID='account-main',
        PRODUCT_PAYOUT_MIN_DELAY_HOURS=0,
    )
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    def test_auto_payout_skips_without_address_and_with_active_refund(self, mock_send):
        admin = self.create_user('skip-admin@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('skip-buyer@example.com')
        seller, store, product = self.create_store_product('skip-owner@example.com', slug='store-skip-payout')
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        self.client.force_authenticate(user=admin)
        self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')
        self.client.force_authenticate(user=seller)
        self.client.post(reverse('seller-product-order-ship', args=[order.order_no]), {'carrier': 'TH', 'tracking_number': 'TN-2'}, format='json')
        self.client.force_authenticate(user=buyer)
        self.client.post(reverse('product-order-confirm-received', args=[order.order_no]), format='json')

        # No payout address -> skipped
        result_no_address = ProductPayoutService().settle_pending_payouts()
        self.assertEqual(result_no_address['skipped_payouts'], 1)
        self.assertFalse(mock_send.called)

        # Add address but active refund -> skipped
        SellerPayoutAddress.objects.create(seller_store=store, address='bAddr', is_default=True, is_active=True)
        ProductRefundRequest.objects.create(
            product_order=order,
            requester=buyer,
            reason='refund',
            status=ProductRefundRequest.STATUS_APPROVED,
            requested_amount='1.00',
            currency='THB-LTT',
        )
        result_with_refund = ProductPayoutService().settle_pending_payouts()
        self.assertGreaterEqual(result_with_refund['skipped_payouts'], 1)

    def test_refund_request_and_admin_transitions(self):
        admin = self.create_user('refund-admin@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('refund-buyer@example.com')
        other_buyer = self.create_user('refund-other@example.com')
        seller, _, product = self.create_store_product('refund-owner@example.com', slug='store-refund')
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        self.client.force_authenticate(user=admin)
        self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')

        self.client.force_authenticate(user=other_buyer)
        forbidden = self.client.post(reverse('product-order-refund-requests', args=[order.order_no]), {'reason': 'x'}, format='json')
        self.assertEqual(forbidden.status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(user=buyer)
        created = self.client.post(
            reverse('product-order-refund-requests', args=[order.order_no]),
            {'reason': 'damaged', 'requested_amount': '5.00'},
            format='json',
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        refund_id = created.data['id']

        self.client.force_authenticate(user=seller)
        seller_list = self.client.get(reverse('seller-refund-request-list'))
        self.assertEqual(seller_list.status_code, status.HTTP_200_OK)
        self.assertEqual(len(seller_list.data), 1)

        self.client.force_authenticate(user=admin)
        approve = self.client.post(reverse('admin-refund-request-approve', args=[refund_id]), {'admin_note': 'ok'}, format='json')
        self.assertEqual(approve.status_code, status.HTTP_200_OK)
        invalid_approve = self.client.post(reverse('admin-refund-request-approve', args=[refund_id]), format='json')
        self.assertEqual(invalid_approve.status_code, status.HTTP_400_BAD_REQUEST)
        reject = self.client.post(reverse('admin-refund-request-reject', args=[refund_id]), {'admin_note': 'no'}, format='json')
        self.assertEqual(reject.status_code, status.HTTP_200_OK)
        mark_refunded = self.client.post(reverse('admin-refund-request-mark-refunded', args=[refund_id]), {'refund_txid': 'tx-refund-1'}, format='json')
        self.assertEqual(mark_refunded.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(
        PRODUCT_AUTO_PAYOUT_ENABLED=True,
        PRODUCT_PAYOUT_WALLET_ID='wallet-main',
        PRODUCT_PAYOUT_ACCOUNT_ID='account-main',
        PRODUCT_PAYOUT_MIN_DELAY_HOURS=0,
    )
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    def test_mark_refunded_prevents_pending_payout(self, mock_send):
        admin = self.create_user('refund2-admin@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('refund2-buyer@example.com')
        seller, store, product = self.create_store_product('refund2-owner@example.com', slug='store-refund2')
        SellerPayoutAddress.objects.create(seller_store=store, address='bRefAddr', is_default=True, is_active=True)
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        self.client.force_authenticate(user=admin)
        self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')
        self.client.force_authenticate(user=seller)
        self.client.post(reverse('seller-product-order-ship', args=[order.order_no]), {'carrier': 'TH', 'tracking_number': 'TN-3'}, format='json')
        self.client.force_authenticate(user=buyer)
        self.client.post(reverse('product-order-confirm-received', args=[order.order_no]), format='json')
        refund = ProductRefundRequest.objects.create(
            product_order=order,
            requester=buyer,
            reason='refund',
            status=ProductRefundRequest.STATUS_APPROVED,
            requested_amount='1.00',
            currency='THB-LTT',
        )
        self.client.force_authenticate(user=admin)
        marked = self.client.post(reverse('admin-refund-request-mark-refunded', args=[refund.id]), {'refund_txid': 'tx-r2'}, format='json')
        self.assertEqual(marked.status_code, status.HTTP_200_OK)
        payout = SellerPayout.objects.get(product_order=order)
        self.assertEqual(payout.status, SellerPayout.STATUS_FAILED)
        ProductPayoutService().settle_pending_payouts()
        self.assertFalse(mock_send.called)

    @override_settings(
        PRODUCT_AUTO_PAYOUT_ENABLED=True,
        PRODUCT_PAYOUT_WALLET_ID='wallet-main',
        PRODUCT_PAYOUT_ACCOUNT_ID='account-main',
        PRODUCT_PAYOUT_MIN_DELAY_HOURS=0,
    )
    @patch('apps.accounts.services.LbryDaemonClient.wallet_send')
    def test_settle_product_payouts_command_prints_summary(self, mock_send):
        admin = self.create_user('cmd-payout-admin@example.com', is_staff=True, is_superuser=True)
        buyer = self.create_user('cmd-payout-buyer@example.com')
        seller, store, product = self.create_store_product('cmd-payout-owner@example.com', slug='store-cmd-payout')
        SellerPayoutAddress.objects.create(seller_store=store, address='bCmdPayout', is_default=True, is_active=True)
        address = self.create_shipping_address(buyer)
        order, _ = self.create_product_order(buyer, product, address)
        self.client.force_authenticate(user=admin)
        self.client.post(reverse('product-order-mark-paid', args=[order.order_no]), format='json')
        self.client.force_authenticate(user=seller)
        self.client.post(reverse('seller-product-order-ship', args=[order.order_no]), {'carrier': 'TH', 'tracking_number': 'TN-4'}, format='json')
        self.client.force_authenticate(user=buyer)
        self.client.post(reverse('product-order-confirm-received', args=[order.order_no]), format='json')
        mock_send.return_value = {'txid': 'tx-cmd-payout'}

        out = StringIO()
        management.call_command('settle_product_payouts', stdout=out)
        rendered = out.getvalue()
        self.assertIn('scanned_payouts=', rendered)
        self.assertIn('eligible_payouts=', rendered)
        self.assertIn('settled_payouts=', rendered)
        self.assertIn('skipped_payouts=', rendered)
        self.assertIn('failed_payouts=', rendered)


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
