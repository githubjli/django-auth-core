from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


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
