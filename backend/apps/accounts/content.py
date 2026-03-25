from __future__ import annotations

"""
Internal unified content representation helpers.

Important:
- This module is an internal backend mapping layer.
- It is NOT a public API contract by itself.
- Existing public contract remains the current /api/videos/* and /api/live/* endpoints.
"""

from rest_framework import serializers

from apps.accounts.models import LiveStream, Video
from apps.accounts.services import AntMediaLiveAdapter


class UnifiedContentSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    content_type = serializers.ChoiceField(choices=['video', 'live'], read_only=True)
    title = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    owner_id = serializers.IntegerField(read_only=True)
    owner_name = serializers.CharField(read_only=True)
    category_slug = serializers.CharField(read_only=True, allow_blank=True)
    category_name = serializers.CharField(read_only=True, allow_blank=True)
    visibility = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    status_source = serializers.CharField(read_only=True)
    thumbnail_url = serializers.CharField(read_only=True, allow_null=True)
    playback_url = serializers.CharField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    is_live = serializers.BooleanField(read_only=True)
    viewer_count = serializers.IntegerField(read_only=True, allow_null=True)
    view_count = serializers.IntegerField(read_only=True, allow_null=True)
    like_count = serializers.IntegerField(read_only=True, allow_null=True)
    comment_count = serializers.IntegerField(read_only=True, allow_null=True)


def map_video_to_content(video: Video, request=None) -> dict:
    thumbnail_url = _build_file_url(getattr(video, 'thumbnail', None), request=request)
    playback_url = _build_file_url(getattr(video, 'file', None), request=request)
    prefetched_view_count = getattr(video, 'view_count', None)

    return {
        'id': video.id,
        'content_type': 'video',
        'title': video.title,
        'description': video.description,
        'owner_id': video.owner_id,
        'owner_name': video.owner.display_name,
        'category_slug': video.category_slug,
        'category_name': video.category_name,
        'visibility': video.visibility,
        'status': video.status,
        'status_source': 'django_control',
        'thumbnail_url': thumbnail_url,
        'playback_url': playback_url,
        'created_at': video.created_at,
        'is_live': False,
        'viewer_count': None,
        'view_count': prefetched_view_count if prefetched_view_count is not None else video.views.count(),
        'like_count': video.like_count,
        'comment_count': video.comment_count,
    }


def map_live_to_content(stream: LiveStream, request=None, adapter: AntMediaLiveAdapter | None = None) -> dict:
    adapter = adapter or AntMediaLiveAdapter()
    normalized = adapter.normalize_stream_fields(stream)

    return {
        'id': stream.id,
        'content_type': 'live',
        'title': stream.title,
        'description': stream.description,
        'owner_id': stream.owner_id,
        'owner_name': stream.owner.display_name,
        'category_slug': stream.category.slug if stream.category else '',
        'category_name': stream.category.name if stream.category else '',
        'visibility': stream.visibility,
        'status': normalized['status'],
        'status_source': normalized['status_source'],
        'thumbnail_url': normalized['thumbnail_url'],
        'playback_url': normalized['playback_url'],
        'created_at': stream.created_at,
        'is_live': normalized['status'] == LiveStream.STATUS_LIVE,
        'viewer_count': normalized['viewer_count'],
        'view_count': None,
        'like_count': None,
        'comment_count': None,
    }


def _build_file_url(field_file, request=None):
    if not field_file:
        return None
    if request is None:
        return field_file.url
    return request.build_absolute_uri(field_file.url)
