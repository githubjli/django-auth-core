from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import LiveStream

User = get_user_model()


class LiveWatchConfigAPITestCase(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(email='ownerwc@example.com', password='pass1234', is_creator=True)

    @patch('apps.accounts.views.AntMediaLiveAdapter._get_websocket_url', return_value='wss://ant.example.com/ws')
    @patch('apps.accounts.views.AntMediaLiveAdapter._get_playback_url', return_value='https://ant.example.com/streams/s.m3u8')
    @patch('apps.accounts.views.AntMediaLiveAdapter.normalize_stream_fields', return_value={'effective_status': 'live', 'viewer_count': 3})
    def test_public_live_anonymous_can_get_watch_config(self, _n, _hls, _ws):
        stream = LiveStream.objects.create(owner=self.owner, title='pub', visibility=LiveStream.VISIBILITY_PUBLIC, status=LiveStream.STATUS_LIVE)
        response = self.client.get(reverse('live-stream-watch-config', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('playback', response.data)
        self.assertEqual(response.data['playback']['stream_id'], stream.stream_key)
        self.assertIn('fallback', response.data)
        self.assertNotIn('publish_session_id', response.data)
        self.assertNotIn('publish_config', response.data)
        self.assertNotIn('stream_key', response.data)

    def test_private_live_anonymous_returns_404(self):
        stream = LiveStream.objects.create(owner=self.owner, title='pri', visibility=LiveStream.VISIBILITY_PRIVATE, status=LiveStream.STATUS_LIVE)
        response = self.client.get(reverse('live-stream-watch-config', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch('apps.accounts.views.AntMediaLiveAdapter._get_websocket_url', return_value='wss://ant.example.com/ws')
    @patch('apps.accounts.views.AntMediaLiveAdapter._get_playback_url', return_value='https://ant.example.com/streams/s.m3u8')
    @patch('apps.accounts.views.AntMediaLiveAdapter.normalize_stream_fields', return_value={'effective_status': 'ended', 'viewer_count': 0})
    def test_private_live_owner_can_get_watch_config_and_ended_connected_false(self, _n, _hls, _ws):
        stream = LiveStream.objects.create(owner=self.owner, title='pri', visibility=LiveStream.VISIBILITY_PRIVATE, status=LiveStream.STATUS_ENDED)
        self.client.force_authenticate(user=self.owner)
        response = self.client.get(reverse('live-stream-watch-config', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['playback']['connected'])

    @patch('apps.accounts.views.AntMediaLiveAdapter._get_websocket_url', return_value=None)
    @patch('apps.accounts.views.AntMediaLiveAdapter._get_playback_url', return_value='https://ant.example.com/streams/s.m3u8')
    @patch('apps.accounts.views.AntMediaLiveAdapter.normalize_stream_fields', return_value={'effective_status': 'live', 'viewer_count': 1})
    def test_missing_websocket_falls_back_hls_mode(self, _n, _hls, _ws):
        stream = LiveStream.objects.create(owner=self.owner, title='pub2', visibility=LiveStream.VISIBILITY_PUBLIC, status=LiveStream.STATUS_LIVE)
        response = self.client.get(reverse('live-stream-watch-config', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['playback']['mode'], 'hls')

    def test_failed_live_returns_error(self):
        stream = LiveStream.objects.create(owner=self.owner, title='f', visibility=LiveStream.VISIBILITY_PUBLIC, status=LiveStream.STATUS_FAILED)
        response = self.client.get(reverse('live-stream-watch-config', args=[stream.id]))
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
