from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


class AuthAPITestCase(APITestCase):
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
        self.client.post(
            reverse('auth-register'),
            {
                'email': 'admin@example.com',
                'password': 'strong-pass-123',
                'first_name': 'Admin',
                'last_name': 'User',
            },
            format='json',
        )
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.get(email='admin@example.com')
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
