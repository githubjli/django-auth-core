from rest_framework import serializers

from apps.accounts.models import DramaEpisode, DramaSeries


class DramaSeriesSerializer(serializers.ModelSerializer):
    cover_url = serializers.SerializerMethodField()
    free_episode_count = serializers.IntegerField(read_only=True)
    locked_episode_count = serializers.IntegerField(read_only=True)
    is_favorited = serializers.SerializerMethodField()
    continue_episode_no = serializers.SerializerMethodField()
    continue_progress_seconds = serializers.SerializerMethodField()

    class Meta:
        model = DramaSeries
        fields = (
            'id',
            'title',
            'description',
            'cover_url',
            'tags',
            'total_episodes',
            'free_episode_count',
            'locked_episode_count',
            'view_count',
            'favorite_count',
            'is_favorited',
            'continue_episode_no',
            'continue_progress_seconds',
        )

    def get_cover_url(self, obj):
        request = self.context.get('request')
        if not getattr(obj, 'cover', None):
            return None
        if not obj.cover:
            return None
        if request is None:
            return obj.cover.url
        return request.build_absolute_uri(obj.cover.url)

    def get_is_favorited(self, _obj):
        return False

    def get_continue_episode_no(self, _obj):
        return None

    def get_continue_progress_seconds(self, _obj):
        return None


class DramaEpisodeSerializer(serializers.ModelSerializer):
    series_id = serializers.IntegerField(source='series.id', read_only=True)
    is_locked = serializers.SerializerMethodField()
    is_unlocked = serializers.SerializerMethodField()
    video_url = serializers.SerializerMethodField()
    hls_url = serializers.SerializerMethodField()

    class Meta:
        model = DramaEpisode
        fields = (
            'id',
            'series_id',
            'episode_no',
            'title',
            'duration_seconds',
            'video_url',
            'hls_url',
            'is_free',
            'unlock_type',
            'meow_points_price',
            'is_locked',
            'is_unlocked',
        )

    def get_is_locked(self, obj):
        return not obj.is_free

    def get_is_unlocked(self, obj):
        return obj.is_free

    def _build_url(self, value):
        if not value:
            return None
        request = self.context.get('request')
        if request is None:
            return value
        if value.startswith('http://') or value.startswith('https://'):
            return value
        return request.build_absolute_uri(value)

    def get_video_url(self, obj):
        if not obj.is_free:
            return None
        if obj.video_url:
            return self._build_url(obj.video_url)
        if obj.video_file:
            request = self.context.get('request')
            if request is None:
                return obj.video_file.url
            return request.build_absolute_uri(obj.video_file.url)
        return None

    def get_hls_url(self, obj):
        if not obj.is_free:
            return None
        return self._build_url(obj.hls_url)
