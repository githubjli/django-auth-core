from rest_framework import serializers

from apps.accounts.models import ChannelSubscription, DramaComment, DramaEpisode, DramaFavorite, DramaSeries, DramaWatchProgress


class DramaSeriesSerializer(serializers.ModelSerializer):
    cover_url = serializers.SerializerMethodField()
    free_episode_count = serializers.IntegerField(read_only=True)
    locked_episode_count = serializers.IntegerField(read_only=True)
    is_favorited = serializers.SerializerMethodField()
    continue_episode_no = serializers.SerializerMethodField()
    continue_progress_seconds = serializers.SerializerMethodField()
    owner_id = serializers.IntegerField(read_only=True, allow_null=True)
    owner_name = serializers.SerializerMethodField()
    owner_avatar_url = serializers.SerializerMethodField()
    viewer_is_subscribed = serializers.SerializerMethodField()
    subscriber_count = serializers.SerializerMethodField()

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
            'comment_count',
            'share_count',
            'gift_count',
            'gift_amount_total',
            'is_favorited',
            'continue_episode_no',
            'continue_progress_seconds',
            'owner_id',
            'owner_name',
            'owner_avatar_url',
            'viewer_is_subscribed',
            'subscriber_count',
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


    def get_owner_name(self, obj):
        if obj.owner_id is None or obj.owner is None:
            return None
        return obj.owner.display_name

    def get_owner_avatar_url(self, obj):
        if obj.owner_id is None or obj.owner is None or not obj.owner.avatar:
            return None
        request = self.context.get('request')
        if request is None:
            return obj.owner.avatar.url
        return request.build_absolute_uri(obj.owner.avatar.url)

    def get_viewer_is_subscribed(self, obj):
        if obj.owner_id is None:
            return False
        subscribed_owner_ids = self.context.get('subscribed_owner_ids')
        if subscribed_owner_ids is not None:
            return obj.owner_id in subscribed_owner_ids
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        return ChannelSubscription.objects.filter(channel_id=obj.owner_id, subscriber=request.user).exists()

    def get_subscriber_count(self, obj):
        if obj.owner_id is None or obj.owner is None:
            return 0
        return obj.owner.subscriber_count

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
    previous_episode_no = serializers.SerializerMethodField()
    next_episode_no = serializers.SerializerMethodField()

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
            'previous_episode_no',
            'next_episode_no',
            'is_free',
            'unlock_type',
            'meow_points_price',
            'meow_credit_price',
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

    def _get_episode_nav_value(self, obj, key):
        episode_nav_by_id = self.context.get('episode_nav_by_id') or {}
        if obj.id in episode_nav_by_id:
            return episode_nav_by_id[obj.id].get(key)
        queryset = DramaEpisode.objects.filter(series_id=obj.series_id, is_active=True).order_by('sort_order', 'episode_no', 'id')
        episode_nos = list(queryset.values_list('episode_no', flat=True))
        try:
            index = episode_nos.index(obj.episode_no)
        except ValueError:
            return None
        if key == 'previous_episode_no':
            return episode_nos[index - 1] if index > 0 else None
        if key == 'next_episode_no':
            return episode_nos[index + 1] if index < len(episode_nos) - 1 else None
        return None

    def get_previous_episode_no(self, obj):
        return self._get_episode_nav_value(obj, 'previous_episode_no')

    def get_next_episode_no(self, obj):
        return self._get_episode_nav_value(obj, 'next_episode_no')

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


class DramaCommentUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    display_name = serializers.CharField()


class DramaCommentSerializer(serializers.ModelSerializer):
    series_id = serializers.IntegerField(source='series.id', read_only=True)
    parent_id = serializers.IntegerField(source='parent.id', allow_null=True, read_only=True)
    user = DramaCommentUserSerializer(read_only=True)

    class Meta:
        model = DramaComment
        fields = (
            'id',
            'series_id',
            'parent_id',
            'content',
            'like_count',
            'reply_count',
            'user',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class DramaCommentCreateSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=500)
    parent_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_content(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('content cannot be blank.')
        return value


class DramaInteractionSummarySerializer(serializers.Serializer):
    series_id = serializers.IntegerField(source='id', read_only=True)
    favorite_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    share_count = serializers.IntegerField(read_only=True)
    gift_count = serializers.IntegerField(read_only=True)
    gift_amount_total = serializers.IntegerField(read_only=True)
    view_count = serializers.IntegerField(read_only=True)
    viewer_is_favorited = serializers.SerializerMethodField()
    viewer_is_subscribed = serializers.SerializerMethodField()
    owner_id = serializers.IntegerField(read_only=True, allow_null=True)
    subscriber_count = serializers.SerializerMethodField()

    def get_viewer_is_favorited(self, obj):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        return DramaFavorite.objects.filter(series=obj, user=request.user).exists()

    def get_viewer_is_subscribed(self, obj):
        request = self.context.get('request')
        if obj.owner_id is None or request is None or not request.user.is_authenticated:
            return False
        return ChannelSubscription.objects.filter(channel_id=obj.owner_id, subscriber=request.user).exists()

    def get_subscriber_count(self, obj):
        if obj.owner_id is None or obj.owner is None:
            return 0
        return obj.owner.subscriber_count


class DramaGiftSendSerializer(serializers.Serializer):
    ALLOWED_AMOUNTS = [1, 10, 30, 100, 200, 500]

    amount = serializers.ChoiceField(choices=ALLOWED_AMOUNTS)
    payment_method = serializers.ChoiceField(
        choices=['meow_points', 'meow_credit'],
        required=False,
        default='meow_points',
    )


class DramaGiftSendResponseSerializer(serializers.Serializer):
    series_id = serializers.IntegerField()
    receiver_id = serializers.IntegerField()
    amount = serializers.IntegerField()
    payment_method = serializers.CharField()
    points_charged = serializers.IntegerField()
    credits_charged = serializers.IntegerField()
    sender_balance = serializers.IntegerField()


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


class DramaEpisodeUnlockRequestSerializer(serializers.Serializer):
    payment_method = serializers.ChoiceField(choices=['meow_points', 'meow_credit'], required=False, default='meow_points')


class DramaUnlockResponseSerializer(serializers.Serializer):
    episode_id = serializers.IntegerField()
    series_id = serializers.IntegerField()
    is_unlocked = serializers.BooleanField()
    payment_method = serializers.CharField(required=False)
    points_charged = serializers.IntegerField()
    credits_charged = serializers.IntegerField(default=0)
    code = serializers.CharField(required=False)


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


class CreatorDramaSeriesSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    cover_url = serializers.SerializerMethodField(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)
    subscriber_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = DramaSeries
        fields = (
            'id', 'owner_id', 'title', 'description', 'cover', 'cover_url', 'category', 'category_name',
            'category_slug', 'tags', 'total_episodes', 'status', 'is_active', 'view_count', 'favorite_count',
            'comment_count', 'share_count', 'gift_count', 'gift_amount_total', 'subscriber_count', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'owner_id', 'view_count', 'favorite_count', 'comment_count', 'share_count', 'gift_count', 'gift_amount_total', 'subscriber_count', 'created_at', 'updated_at')

    def get_cover_url(self, obj):
        request = self.context.get('request')
        if not obj.cover:
            return None
        return request.build_absolute_uri(obj.cover.url) if request else obj.cover.url

    def get_subscriber_count(self, obj):
        if obj.owner_id is None or obj.owner is None:
            return 0
        return obj.owner.subscriber_count

    def validate_tags(self, value):
        if isinstance(value, str):
            return [item.strip() for item in value.split(',') if item.strip()]
        return value


class CreatorDramaEpisodeSerializer(serializers.ModelSerializer):
    series_id = serializers.IntegerField(source='series.id', read_only=True)
    points_price = serializers.IntegerField(source='meow_points_price', required=False)
    coin_price = serializers.IntegerField(write_only=True, required=False)
    meow_credit_price = serializers.IntegerField(required=False, min_value=0)

    class Meta:
        model = DramaEpisode
        fields = (
            'id', 'series_id', 'episode_no', 'title', 'description', 'video_file', 'video_url', 'hls_url', 'thumbnail',
            'duration_seconds', 'is_free', 'unlock_type', 'meow_points_price', 'meow_credit_price', 'points_price', 'coin_price', 'sort_order',
            'status', 'is_active', 'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'series_id', 'created_at', 'updated_at')

    def validate(self, attrs):
        if 'coin_price' in attrs and 'meow_points_price' not in attrs:
            attrs['meow_points_price'] = attrs.pop('coin_price')
        unlock_type = attrs.get('unlock_type', getattr(self.instance, 'unlock_type', DramaEpisode.UNLOCK_MEOW_POINTS))
        if unlock_type == DramaEpisode.UNLOCK_FREE:
            attrs['is_free'] = True
            attrs['meow_points_price'] = 0
            attrs['meow_credit_price'] = 0
        elif unlock_type == DramaEpisode.UNLOCK_MEOW_POINTS:
            attrs['is_free'] = False
            attrs['meow_points_price'] = attrs.get('meow_points_price', getattr(self.instance, 'meow_points_price', 0))
            attrs['meow_credit_price'] = attrs.get('meow_credit_price', getattr(self.instance, 'meow_credit_price', 0))
        return attrs
