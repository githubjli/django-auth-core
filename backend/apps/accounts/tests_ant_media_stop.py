from urllib import error
from unittest.mock import patch

from django.test import TestCase, override_settings

from apps.accounts.services import AntMediaLiveAdapter


@override_settings(ANT_MEDIA_BASE_URL='https://ant.example.com', ANT_MEDIA_REST_APP_NAME='LiveApp')
class AntMediaStopBroadcastTestCase(TestCase):
    @patch('apps.accounts.services.urllib_request.urlopen')
    def test_stop_broadcast_uses_application_json_request(self, mock_urlopen):
        response = mock_urlopen.return_value.__enter__.return_value
        response.read.return_value = b'{"success":true}'
        response.status = 200

        result = AntMediaLiveAdapter().stop_broadcast('stream-1')

        self.assertTrue(result['ok'])
        request_obj = mock_urlopen.call_args[0][0]
        self.assertEqual(request_obj.get_method(), 'POST')
        self.assertEqual(request_obj.data, b'{}')
        self.assertEqual(request_obj.headers.get('Content-type'), 'application/json')
        self.assertEqual(request_obj.headers.get('Accept'), 'application/json')

    @patch('apps.accounts.services.urllib_request.urlopen')
    def test_stop_broadcast_http_415_returns_warning(self, mock_urlopen):
        mock_urlopen.side_effect = error.HTTPError(
            url='https://ant.example.com/LiveApp/rest/v2/broadcasts/stream-1/stop',
            code=415,
            msg='Unsupported Media Type',
            hdrs=None,
            fp=None,
        )

        result = AntMediaLiveAdapter().stop_broadcast('stream-1')

        self.assertFalse(result['ok'])
        self.assertEqual(result['warning'], 'ant_media_stop_failed')
        self.assertEqual(result['status_code'], 415)
