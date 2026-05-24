from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import LiveStream
from apps.accounts.services import AntMediaLiveAdapter


class Command(BaseCommand):
    help = 'Synchronize live stream status from Ant Media for active Django live streams.'

    def handle(self, *args, **options):
        adapter = AntMediaLiveAdapter()
        threshold = self._threshold()
        checked = 0
        ended = 0
        warnings = 0

        now = timezone.now()
        ready_timeout = now - timedelta(minutes=5)
        for stream in LiveStream.objects.filter(status__in=[LiveStream.STATUS_LIVE, LiveStream.STATUS_READY]).iterator():
            checked += 1
            if stream.status == LiveStream.STATUS_READY and stream.publish_started_at and stream.publish_started_at < ready_timeout:
                stream.status = LiveStream.STATUS_FAILED
                stream.failure_reason = 'ready_timeout'
                stream.save(update_fields=['status', 'failure_reason'])
                ended += 1
                continue
            normalized = adapter.normalize_stream_fields(
                stream,
                persist_no_signal=True,
                require_sync_enabled=False,
            )
            ant_status = normalized.get('ant_media_status')
            should_end = normalized.get('should_end')
            if ant_status == 'finished' or should_end:
                stream.status = LiveStream.STATUS_ENDED
                stream.ended_at = timezone.now()
                stream.ant_media_no_signal_count = 0
                stream.save(update_fields=['status', 'ended_at', 'ant_media_no_signal_count'])
                ended += 1
            elif not normalized.get('sync_ok'):
                warnings += 1
                self.stderr.write(
                    f"Unable to sync live_id={stream.id}: {normalized.get('sync_error') or 'unknown_error'}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'Checked {checked} live stream(s); ended {ended}; warnings {warnings}; threshold {threshold}.'
            )
        )

    def _threshold(self):
        from django.conf import settings

        return getattr(settings, 'ANT_MEDIA_NO_SIGNAL_END_THRESHOLD', 3)
