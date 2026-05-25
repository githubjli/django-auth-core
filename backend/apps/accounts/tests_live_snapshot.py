from unittest.mock import patch

from django.core.files.base import ContentFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import LiveStream
from apps.accounts.serializers import LiveStreamSerializer


class LiveSnapshotTestCase(APITestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        self.creator = User.objects.create_user(email='snap@example.com', password='pass1234', is_creator=True)

    @patch('apps.accounts.views.LiveStreamStatusAPIView._trigger_async_snapshot')
    @patch('apps.accounts.views.AntMediaLiveAdapter.get_broadcast_status', return_value={'ant_media_status': 'broadcasting', 'sync_ok': True, 'sync_error': None})
    def test_start_triggers_snapshot_task(self, _mock_status, mock_trigger):
        stream = LiveStream.objects.create(owner=self.creator, title='s', status=LiveStream.STATUS_READY)
        self.client.force_authenticate(user=self.creator)
        response = self.client.post(reverse('live-stream-start', args=[stream.id]), format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_trigger.assert_called_once_with(stream.id)

    @patch('apps.accounts.services.subprocess.run')
    @patch('apps.accounts.services.shutil.which', return_value='/usr/bin/ffmpeg')
    @patch('apps.accounts.services.AntMediaLiveAdapter.get_playback_url', return_value='https://x/stream.m3u8')
    @patch('apps.accounts.services.AntMediaLiveAdapter._get_preview_image_url', return_value='https://x/preview.png')
    @patch('apps.accounts.services.urllib_request.urlopen')
    def test_capture_failure_does_not_change_live_status(self, mock_urlopen, _preview, _pb, _which, mock_run):
        mock_urlopen.side_effect = Exception('unavailable')
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = 'failed'
        stream = LiveStream.objects.create(owner=self.creator, title='s', status=LiveStream.STATUS_LIVE)
        from apps.accounts.services import capture_live_snapshot
        capture_live_snapshot(stream)
        stream.refresh_from_db()
        self.assertEqual(stream.status, LiveStream.STATUS_LIVE)
        self.assertEqual(stream.thumbnail_capture_status, LiveStream.THUMBNAIL_CAPTURE_FAILED)

    def test_serializer_prefers_local_thumbnail(self):
        stream = LiveStream.objects.create(owner=self.creator, title='s', status=LiveStream.STATUS_LIVE)
        stream.thumbnail.save('t.jpg', ContentFile(b'abc'), save=True)
        data = LiveStreamSerializer(stream).data
        self.assertTrue(data['thumbnail_url'])

    @patch('apps.accounts.services.shutil.which', return_value='/usr/bin/ffmpeg')
    @patch('apps.accounts.services.AntMediaLiveAdapter.get_playback_url', return_value='https://x/stream.m3u8')
    @patch('apps.accounts.services.AntMediaLiveAdapter._get_preview_image_url', return_value=None)
    @patch('apps.accounts.services.urllib_request.urlopen')
    @patch('apps.accounts.services.subprocess.run')
    def test_capture_uses_hls_without_ss_and_with_rw_timeout(self, mock_run, mock_urlopen, _preview, _pb, _which):
        probe_resp = mock_urlopen.return_value.__enter__.return_value
        probe_resp.status = 200
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = 'failed'
        stream = LiveStream.objects.create(owner=self.creator, title='s', status=LiveStream.STATUS_LIVE)
        from apps.accounts.services import capture_live_snapshot
        capture_live_snapshot(stream)
        cmd = mock_run.call_args[0][0]
        self.assertIn('-rw_timeout', cmd)
        self.assertIn('10000000', cmd)
        self.assertNotIn('-ss', cmd)
