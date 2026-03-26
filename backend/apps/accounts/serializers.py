from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.models import (
    Category,
    ChannelSubscription,
    LiveStream,
    Video,
    VideoComment,
    VideoLike,
)
from apps.accounts.services import AntMediaLiveAdapter

User = get_user_model()
LEGACY_CATEGORY_SLUG_ALIASES = {
    'tech': 'technology',
}


class OptionalSlugRelatedField(serializers.SlugRelatedField):
    def to_internal_value(self, data):
        if data in (None, ''):
            return None
        data = LEGACY_CATEGORY_SLUG_ALIASES.get(data, data)
        return super().to_internal_value(data)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name')
        read_only_fields = ('id',)


class AccountProfileSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'display_name',
            'first_name',
            'last_name',
            'avatar',
            'avatar_url',
            'bio',
        )

    def get_avatar_url(self, obj):
        request = self.context.get('request')
        if not obj.avatar:
            return None
        if request is None:
            return obj.avatar.url
        return request.build_absolute_uri(obj.avatar.url)


class AccountPreferencesSerializer(serializers.ModelSerializer):
    LANGUAGE_CHOICES = {'en-US', 'zh-CN', 'th-TH', 'my-MM'}
    THEME_CHOICES = {'light', 'dark', 'system'}

    class Meta:
        model = User
        fields = (
            'language',
            'theme',
            'timezone',
        )

    def validate_language(self, value):
        if value not in self.LANGUAGE_CHOICES:
            raise serializers.ValidationError('Unsupported language.')
        return value

    def validate_theme(self, value):
        if value not in self.THEME_CHOICES:
            raise serializers.ValidationError('Unsupported theme.')
        return value


class EngagementUserSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='display_name', read_only=True)
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'name', 'avatar_url')
        read_only_fields = fields

    def get_avatar_url(self, obj):
        return None


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ('id', 'email', 'password', 'first_name', 'last_name')
        read_only_fields = ('id',)

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User.objects.create_user(password=password, **validated_data)
        return user


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    username_field = User.EMAIL_FIELD


class AdminUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            'id',
            'email',
            'first_name',
            'last_name',
            'is_active',
            'is_staff',
            'is_superuser',
            'date_joined',
        )
        read_only_fields = ('id', 'date_joined')


class PublicCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('name', 'slug', 'description', 'sort_order', 'show_on_homepage')


class VideoSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    owner_name = serializers.CharField(source='owner.display_name', read_only=True)
    owner_avatar_url = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    description_preview = serializers.SerializerMethodField()
    category_name = serializers.CharField(read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)
    like_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    view_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    category = OptionalSlugRelatedField(
        slug_field='slug',
        queryset=Category.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = Video
        fields = (
            'id',
            'owner_id',
            'owner_name',
            'owner_avatar_url',
            'title',
            'description',
            'description_preview',
            'category',
            'category_name',
            'category_slug',
            'like_count',
            'comment_count',
            'view_count',
            'is_liked',
            'file',
            'file_url',
            'thumbnail',
            'thumbnail_url',
            'created_at',
        )
        read_only_fields = (
            'id',
            'owner_id',
            'owner_name',
            'owner_avatar_url',
            'category_name',
            'category_slug',
            'like_count',
            'comment_count',
            'view_count',
            'is_liked',
            'file_url',
            'thumbnail_url',
            'created_at',
        )

    def get_owner_avatar_url(self, obj):
        return None

    def get_file_url(self, obj):
        return self._build_absolute_file_url(obj.file)

    def get_thumbnail_url(self, obj):
        return self._build_absolute_file_url(obj.thumbnail)

    def get_view_count(self, obj):
        prefetched = getattr(obj, 'view_count', None)
        if prefetched is not None:
            return prefetched
        return obj.views.count()

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request is None or not getattr(request, 'user', None) or not request.user.is_authenticated:
            return False
        prefetched = getattr(obj, 'is_liked_value', None)
        if prefetched is not None:
            return bool(prefetched)
        return VideoLike.objects.filter(video=obj, user=request.user).exists()

    def get_description_preview(self, obj):
        if not obj.description:
            return ''
        preview = obj.description.strip()
        if len(preview) <= 140:
            return preview
        return f'{preview[:137].rstrip()}...'

    def _build_absolute_file_url(self, field_file):
        request = self.context.get('request')
        if not field_file:
            return None
        if request is None:
            return field_file.url
        return request.build_absolute_uri(field_file.url)




class LiveStreamSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    owner_name = serializers.CharField(source='owner.display_name', read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)
    category = OptionalSlugRelatedField(
        slug_field='slug',
        queryset=Category.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )
    rtmp_url = serializers.SerializerMethodField()
    playback_url = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    preview_image_url = serializers.SerializerMethodField()
    snapshot_url = serializers.SerializerMethodField()
    status_source = serializers.SerializerMethodField()
    viewer_count = serializers.SerializerMethodField()
    django_status = serializers.SerializerMethodField()
    effective_status = serializers.SerializerMethodField()
    raw_ant_media_status = serializers.SerializerMethodField()
    sync_ok = serializers.SerializerMethodField()
    sync_error = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()
    can_start = serializers.SerializerMethodField()
    can_end = serializers.SerializerMethodField()

    class Meta:
        model = LiveStream
        fields = (
            'id',
            'owner_id',
            'owner_name',
            'title',
            'description',
            'payment_address',
            'category',
            'category_name',
            'visibility',
            'status',
            'django_status',
            'effective_status',
            'status_source',
            'raw_ant_media_status',
            'stream_key',
            'rtmp_url',
            'playback_url',
            'thumbnail_url',
            'preview_image_url',
            'snapshot_url',
            'viewer_count',
            'can_start',
            'can_end',
            'sync_ok',
            'sync_error',
            'message',
            'started_at',
            'ended_at',
            'created_at',
        )
        read_only_fields = (
            'id',
            'owner_id',
            'owner_name',
            'category_name',
            'status',
            'django_status',
            'effective_status',
            'status_source',
            'raw_ant_media_status',
            'stream_key',
            'rtmp_url',
            'playback_url',
            'thumbnail_url',
            'preview_image_url',
            'snapshot_url',
            'viewer_count',
            'can_start',
            'can_end',
            'sync_ok',
            'sync_error',
            'message',
            'started_at',
            'ended_at',
            'created_at',
        )

    def get_rtmp_url(self, obj):
        return self._normalized(obj).get('rtmp_url')

    def get_playback_url(self, obj):
        return self._normalized(obj).get('playback_url')

    def get_thumbnail_url(self, obj):
        return self._normalized(obj).get('thumbnail_url')

    def get_preview_image_url(self, obj):
        return self._normalized(obj).get('preview_image_url')

    def get_snapshot_url(self, obj):
        return self._normalized(obj).get('snapshot_url')

    def get_status_source(self, obj):
        return self._normalized(obj).get('status_source')

    def get_status(self, obj):
        return self._normalized(obj).get('status')

    def get_viewer_count(self, obj):
        return self._normalized(obj).get('viewer_count')

    def get_django_status(self, obj):
        return self._normalized(obj).get('django_status')

    def get_effective_status(self, obj):
        return self._normalized(obj).get('effective_status')

    def get_raw_ant_media_status(self, obj):
        return self._normalized(obj).get('raw_ant_media_status')

    def get_sync_ok(self, obj):
        return self._normalized(obj).get('sync_ok')

    def get_sync_error(self, obj):
        return self._normalized(obj).get('sync_error')

    def get_message(self, obj):
        return self._normalized(obj).get('message')

    def get_can_start(self, obj):
        return self._normalized(obj).get('can_start')

    def get_can_end(self, obj):
        return self._normalized(obj).get('can_end')

    def _normalized(self, obj):
        normalized = getattr(obj, '_normalized_live_fields', None)
        if normalized is not None:
            return normalized
        adapter = AntMediaLiveAdapter()
        normalized = adapter.normalize_stream_fields(obj)
        obj._normalized_live_fields = normalized
        return normalized


class AdminVideoSerializer(VideoSerializer):
    owner_email = serializers.EmailField(source='owner.email', read_only=True)

    class Meta(VideoSerializer.Meta):
        fields = (
            'id',
            'title',
            'thumbnail_url',
            'owner_id',
            'owner_name',
            'owner_email',
            'category',
            'status',
            'visibility',
            'like_count',
            'comment_count',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'thumbnail_url',
            'owner_id',
            'owner_name',
            'owner_email',
            'like_count',
            'comment_count',
            'created_at',
            'updated_at',
        )

class VideoInteractionSummarySerializer(serializers.Serializer):
    video_id = serializers.IntegerField(source='id', read_only=True)
    like_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    viewer_has_liked = serializers.SerializerMethodField()
    viewer_is_subscribed = serializers.SerializerMethodField()
    channel_id = serializers.IntegerField(source='owner.id', read_only=True)
    subscriber_count = serializers.IntegerField(source='owner.subscriber_count', read_only=True)

    def get_viewer_has_liked(self, obj):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        prefetched = getattr(obj, 'is_liked_value', None)
        if prefetched is not None:
            return bool(prefetched)
        return VideoLike.objects.filter(video=obj, user=request.user).exists()

    def get_viewer_is_subscribed(self, obj):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        prefetched = getattr(obj, 'is_subscribed_value', None)
        if prefetched is not None:
            return bool(prefetched)
        return ChannelSubscription.objects.filter(channel=obj.owner, subscriber=request.user).exists()


class VideoCommentSerializer(serializers.ModelSerializer):
    video_id = serializers.IntegerField(source='video.id', read_only=True)
    parent_id = serializers.IntegerField(source='parent.id', allow_null=True, read_only=True)
    viewer_has_liked = serializers.SerializerMethodField()
    user = EngagementUserSerializer(read_only=True)

    class Meta:
        model = VideoComment
        fields = (
            'id',
            'video_id',
            'parent_id',
            'content',
            'created_at',
            'updated_at',
            'like_count',
            'reply_count',
            'viewer_has_liked',
            'user',
        )
        read_only_fields = fields

    def get_viewer_has_liked(self, obj):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        prefetched = getattr(obj, 'viewer_has_liked_value', None)
        if prefetched is not None:
            return bool(prefetched)
        return obj.likes.filter(user=request.user).exists()


class VideoCommentCreateSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=500)
    parent_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_content(self, value):
        trimmed = value.strip()
        if not trimmed:
            raise serializers.ValidationError('content cannot be blank.')
        return trimmed


class VideoMetadataSerializer(VideoSerializer):
    class Meta(VideoSerializer.Meta):
        read_only_fields = (
            'id',
            'owner_id',
            'owner_name',
            'owner_avatar_url',
            'file',
            'file_url',
            'category_name',
            'category_slug',
            'like_count',
            'comment_count',
            'view_count',
            'is_liked',
            'thumbnail_url',
            'created_at',
        )
