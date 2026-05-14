from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import User


class AccountLibraryAPITestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='library@example.com', password='strong-pass-123')
        self.client.force_authenticate(user=self.user)

    def assert_paginated_response(self, response):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data.keys()), {'count', 'next', 'previous', 'results'})
        self.assertEqual(response.data['count'], 0)
        self.assertIsNone(response.data['next'])
        self.assertIsNone(response.data['previous'])
        self.assertEqual(response.data['results'], [])

    def test_library_history_returns_paginated_response(self):
        response = self.client.get(reverse('account-library-history'), {'page': 1, 'page_size': 10})

        self.assert_paginated_response(response)

    def test_library_liked_returns_paginated_response(self):
        response = self.client.get(reverse('account-library-liked'), {'page': 1, 'page_size': 10})

        self.assert_paginated_response(response)

    def test_library_purchased_returns_paginated_response(self):
        response = self.client.get(reverse('account-library-purchased'), {'page': 1, 'page_size': 10})

        self.assert_paginated_response(response)

    def test_library_gifts_sent_returns_paginated_response(self):
        response = self.client.get(reverse('account-library-gifts-sent'), {'page': 1, 'page_size': 10})

        self.assert_paginated_response(response)

    def test_library_gifts_received_returns_paginated_response(self):
        response = self.client.get(reverse('account-library-gifts-received'), {'page': 1, 'page_size': 10})

        self.assert_paginated_response(response)
