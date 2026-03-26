import base64
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from urllib import error, request as urllib_request
from uuid import uuid4

from django.conf import settings
from django.core.files.base import ContentFile

from apps.accounts.models import LiveStream


DEFAULT_THUMBNAIL_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn4n/4AAAAASUVORK5CYII='
)


class AntMediaLiveAdapter:
    STATUS_MAP = {
        'broadcasting': LiveStream.STATUS_LIVE,
        'finished': LiveStream.STATUS_ENDED,
    }

    def normalize_stream_fields(self, stream: LiveStream) -> dict:
        sync = self._fetch_broadcast_payload(stream.stream_key)
        payload = sync.get('payload')
        ant_status = payload.get('status') if payload else None
        mapped_status = self.STATUS_MAP.get(ant_status)

        if mapped_status and stream.status != mapped_status:
            stream.status = mapped_status
            stream.save(update_fields=['status'])

        django_status = stream.status
        effective_status = self._normalize_status(django_status, ant_status)
        status_source = 'ant_media' if ant_status is not None else 'django_control'

        return {
            'status': effective_status,
            'django_status': django_status,
            'effective_status': effective_status,
            'status_source': status_source,
            'raw_ant_media_status': ant_status,
            'rtmp_url': self._get_rtmp_url(),
            'playback_url': self._get_playback_url(stream.stream_key),
            'thumbnail_url': self._get_preview_image_url(stream.stream_key),
            'preview_image_url': self._get_preview_image_url(stream.stream_key),
            'snapshot_url': self._get_preview_image_url(stream.stream_key),
            'viewer_count': self._normalize_viewer_count(payload, fallback=stream.viewer_count),
            'sync_ok': sync.get('sync_ok', False),
            'sync_error': sync.get('sync_error'),
            'message': self._build_message(
                effective_status=effective_status,
                status_source=status_source,
                sync_ok=sync.get('sync_ok', False),
            ),
            'can_start': effective_status != LiveStream.STATUS_LIVE,
            'can_end': effective_status != LiveStream.STATUS_ENDED,
        }

    def get_browser_publish_config(self, stream: LiveStream) -> dict:
        stream_id = stream.stream_key
        websocket_url = self._get_websocket_url()
        adaptor_script_url = self._get_adaptor_script_url()
        app_name = settings.ANT_MEDIA_APP_NAME or None
        if not stream_id or not websocket_url or not adaptor_script_url:
            return {
                'ok': False,
                'error': 'ant_media_publish_config_unavailable',
                'message': 'Ant Media publish config is unavailable. Check backend Ant Media settings.',
            }
        return {
            'ok': True,
            'config': {
                'websocket_url': websocket_url,
                'adaptor_script_url': adaptor_script_url,
                'stream_id': stream_id,
                'app_name': app_name,
                'publish_mode': 'webrtc',
            },
        }

    def _normalize_status(self, db_status: str, ant_status: str | None) -> str:
        if ant_status is not None:
            if ant_status == 'broadcasting':
                return LiveStream.STATUS_LIVE
            if ant_status == 'finished':
                return LiveStream.STATUS_ENDED
            return 'waiting_for_signal'
        if db_status == LiveStream.STATUS_LIVE:
            return LiveStream.STATUS_LIVE
        if db_status == LiveStream.STATUS_ENDED:
            return LiveStream.STATUS_ENDED
        return 'ready'

    def _normalize_viewer_count(self, payload: dict | None, fallback: int) -> int:
        if not payload:
            return fallback
        keys = ('hlsViewerCount', 'webRTCViewerCount', 'rtmpViewerCount')
        total = 0
        has_metric = False
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            try:
                total += int(value)
                has_metric = True
            except (TypeError, ValueError):
                continue
        return total if has_metric else fallback

    def _fetch_broadcast_payload(self, stream_key: str) -> dict:
        if not settings.ANT_MEDIA_SYNC_STATUS:
            return {'payload': None, 'sync_ok': False, 'sync_error': 'sync_disabled'}
        if not settings.ANT_MEDIA_BASE_URL or not settings.ANT_MEDIA_REST_APP_NAME:
            return {'payload': None, 'sync_ok': False, 'sync_error': 'ant_media_not_configured'}

        endpoint = (
            f"{settings.ANT_MEDIA_BASE_URL}/"
            f"{settings.ANT_MEDIA_REST_APP_NAME}/rest/v2/broadcasts/{stream_key}"
        )
        try:
            with urllib_request.urlopen(endpoint, timeout=2) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (error.URLError, TimeoutError):
            return {'payload': None, 'sync_ok': False, 'sync_error': 'ant_media_unavailable'}
        except (ValueError, json.JSONDecodeError):
            return {'payload': None, 'sync_ok': False, 'sync_error': 'invalid_ant_media_payload'}
        if not isinstance(payload, dict):
            return {'payload': None, 'sync_ok': False, 'sync_error': 'invalid_ant_media_payload'}
        return {'payload': payload, 'sync_ok': True, 'sync_error': None}

    def _build_message(self, *, effective_status: str, status_source: str, sync_ok: bool) -> str:
        if status_source == 'ant_media' and effective_status == 'waiting_for_signal':
            return 'Ant Media session exists but is not yet broadcasting.'
        if not sync_ok:
            return 'Using Django control state because Ant Media status is unavailable.'
        if effective_status == LiveStream.STATUS_LIVE:
            return 'Stream is live.'
        if effective_status == LiveStream.STATUS_ENDED:
            return 'Stream has ended.'
        return 'Stream is ready to start.'

    def _get_rtmp_url(self) -> str | None:
        return settings.ANT_MEDIA_RTMP_BASE or None

    def _get_playback_url(self, stream_key: str) -> str | None:
        playback_base = settings.ANT_MEDIA_PLAYBACK_BASE
        if not playback_base and settings.ANT_MEDIA_BASE_URL:
            playback_base = f"{settings.ANT_MEDIA_BASE_URL}/{settings.ANT_MEDIA_APP_NAME}/streams"
        if not playback_base:
            return None
        return f"{playback_base}/{stream_key}.m3u8"

    def _get_preview_image_url(self, stream_key: str) -> str | None:
        if not settings.ANT_MEDIA_PREVIEW_BASE:
            return None
        return f"{settings.ANT_MEDIA_PREVIEW_BASE}/{stream_key}.png"

    def _get_websocket_url(self) -> str | None:
        explicit = getattr(settings, 'ANT_MEDIA_WEBSOCKET_URL', '')
        if explicit:
            return explicit.rstrip('/')
        base_url = settings.ANT_MEDIA_BASE_URL or ''
        app_name = settings.ANT_MEDIA_APP_NAME or ''
        if not base_url or not app_name:
            return None
        parsed = urlparse(base_url)
        if parsed.scheme not in {'http', 'https', 'ws', 'wss'} or not parsed.netloc:
            return None
        scheme = {'http': 'ws', 'https': 'wss'}.get(parsed.scheme, parsed.scheme)
        return f'{scheme}://{parsed.netloc}/{app_name}/websocket'

    def _get_adaptor_script_url(self) -> str | None:
        explicit = getattr(settings, 'ANT_MEDIA_ADAPTOR_SCRIPT_URL', '')
        if explicit:
            return explicit.rstrip('/')
        base_url = settings.ANT_MEDIA_BASE_URL or ''
        app_name = settings.ANT_MEDIA_APP_NAME or ''
        if not base_url or not app_name:
            return None
        return f'{base_url}/{app_name}/js/webrtc_adaptor.js'


def generate_video_thumbnail(video, time_offset: float = 1.0) -> bool:
    if not video.file:
        return False

    thumbnail_content = _extract_thumbnail_with_ffmpeg(video, time_offset=time_offset)
    if thumbnail_content is None:
        thumbnail_content = ContentFile(DEFAULT_THUMBNAIL_PNG)

    filename = f'video_{video.pk or "new"}_{uuid4().hex}.png'
    if video.thumbnail:
        video.thumbnail.delete(save=False)
    video.thumbnail.save(filename, thumbnail_content, save=False)
    return True


def _extract_thumbnail_with_ffmpeg(video, time_offset: float):
    ffmpeg_path = shutil.which('ffmpeg')
    if not ffmpeg_path:
        return None

    try:
        input_path = Path(video.file.path)
    except (NotImplementedError, ValueError):
        return None

    with tempfile.TemporaryDirectory() as temp_dir:
        output_path = Path(temp_dir) / 'thumbnail.png'
        for offset in (max(time_offset, 0), 0):
            completed = subprocess.run(
                [
                    ffmpeg_path,
                    '-y',
                    '-ss',
                    str(offset),
                    '-i',
                    str(input_path),
                    '-frames:v',
                    '1',
                    str(output_path),
                ],
                capture_output=True,
                text=True,
            )
            if completed.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                return ContentFile(output_path.read_bytes())

    return None
