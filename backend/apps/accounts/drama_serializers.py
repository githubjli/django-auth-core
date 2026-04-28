from rest_framework import serializers

from apps.accounts.models import DramaEpisode, DramaFavorite, DramaSeries, DramaWatchProgress


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
        favorite_series_ids = self.context.get('favorite_series_ids')
        if favorite_series_ids is None:
            return False
        return _obj.id in favorite_series_ids

    def get_continue_episode_no(self, _obj):
        progress_by_series_id = self.context.get('progress_by_series_id')
        if not progress_by_series_id:
            return None
        progress = progress_by_series_id.get(_obj.id)
        if progress is None or progress.episode_id is None:
            return None
        return progress.episode.episode_no

    def get_continue_progress_seconds(self, _obj):
        progress_by_series_id = self.context.get('progress_by_series_id')
        if not progress_by_series_id:
            return None
        progress = progress_by_series_id.get(_obj.id)
        if progress is None:
            return None
        return progress.progress_seconds


class DramaEpisodeSerializer(serializers.ModelSerializer):
    series_id = serializers.IntegerField(source='series.id', read_only=True)
    can_watch = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    is_unlocked = serializers.SerializerMethodField()
    points_price = serializers.IntegerField(source='meow_points_price', read_only=True)
    playback_url = serializers.SerializerMethodField()
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
            'can_watch',
            'playback_url',
            'video_url',
            'hls_url',
            'is_free',
            'unlock_type',
            'meow_points_price',
            'points_price',
            'is_locked',
            'is_unlocked',
        )

    def _can_watch(self, obj):
        if obj.is_free:
            return True
        unlocked_episode_ids = self.context.get('unlocked_episode_ids') or set()
        if obj.id in unlocked_episode_ids:
            return True
        if obj.unlock_type == DramaEpisode.UNLOCK_MEMBERSHIP and self.context.get('has_active_membership', False):
            return True
        return False

    def get_can_watch(self, obj):
        return self._can_watch(obj)

    def get_is_locked(self, obj):
        return not self._can_watch(obj)

    def get_is_unlocked(self, obj):
        return self._can_watch(obj)

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
        if not self._can_watch(obj):
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
        if not self._can_watch(obj):
            return None
        return self._build_url(obj.hls_url)

    def get_playback_url(self, obj):
        if not self._can_watch(obj):
            return None
        if obj.hls_url:
            return self._build_url(obj.hls_url)
        return self.get_video_url(obj)


class DramaProgressSaveSerializer(serializers.Serializer):
    episode_id = serializers.IntegerField(min_value=1)
    progress_seconds = serializers.IntegerField(min_value=0)
    completed = serializers.BooleanField()


class DramaWatchProgressSerializer(serializers.ModelSerializer):
    series_id = serializers.IntegerField(source='series.id', read_only=True)
    episode_id = serializers.IntegerField(source='episode.id', read_only=True)
    episode_no = serializers.IntegerField(source='episode.episode_no', read_only=True)

    class Meta:
        model = DramaWatchProgress
        fields = (
            'series_id',
            'episode_id',
            'episode_no',
            'progress_seconds',
            'completed',
            'updated_at',
        )


class DramaFavoriteStateSerializer(serializers.Serializer):
    series_id = serializers.IntegerField()
    is_favorited = serializers.BooleanField()
    favorite_count = serializers.IntegerField()


class DramaUnlockResponseSerializer(serializers.Serializer):
    episode_id = serializers.IntegerField()
    series_id = serializers.IntegerField()
    is_unlocked = serializers.BooleanField()
    points_charged = serializers.IntegerField()


class AccountDramaProgressItemSerializer(serializers.ModelSerializer):
    series_id = serializers.IntegerField(source='series.id', read_only=True)
    series_title = serializers.CharField(source='series.title', read_only=True)
    cover_url = serializers.SerializerMethodField()
    episode_id = serializers.IntegerField(source='episode.id', read_only=True)
    episode_no = serializers.IntegerField(source='episode.episode_no', read_only=True)
    duration_seconds = serializers.IntegerField(source='episode.duration_seconds', read_only=True)

    class Meta:
        model = DramaWatchProgress
        fields = (
            'series_id',
            'series_title',
            'cover_url',
            'episode_id',
            'episode_no',
            'progress_seconds',
            'duration_seconds',
            'updated_at',
        )

    def get_cover_url(self, obj):
        request = self.context.get('request')
        if not getattr(obj.series, 'cover', None):
            return None
        if request is None:
            return obj.series.cover.url
        return request.build_absolute_uri(obj.series.cover.url)


class AccountDramaFavoriteItemSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source='series.id', read_only=True)
    title = serializers.CharField(source='series.title', read_only=True)
    cover_url = serializers.SerializerMethodField()
    total_episodes = serializers.IntegerField(source='series.total_episodes', read_only=True)
    favorited_at = serializers.DateTimeField(source='created_at', read_only=True)

    class Meta:
        model = DramaFavorite
        fields = (
            'id',
            'title',
            'cover_url',
            'total_episodes',
            'favorited_at',
        )

    def get_cover_url(self, obj):
        request = self.context.get('request')
        if not getattr(obj.series, 'cover', None):
            return None
        if request is None:
            return obj.series.cover.url
        return request.build_absolute_uri(obj.series.cover.url)
