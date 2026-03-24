import json
from urllib import error, request as urllib_request

from django.conf import settings
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
    display_name = serializers.CharField(source='display_name', read_only=True)
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

    class Meta:
        model = LiveStream
        fields = (
            'id',
            'owner_id',
            'owner_name',
            'title',
            'description',
            'category',
            'category_name',
            'visibility',
            'status',
            'status_source',
            'stream_key',
            'rtmp_url',
            'playback_url',
            'thumbnail_url',
            'preview_image_url',
            'snapshot_url',
            'viewer_count',
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
            'status_source',
            'stream_key',
            'rtmp_url',
            'playback_url',
            'thumbnail_url',
            'preview_image_url',
            'snapshot_url',
            'viewer_count',
            'started_at',
            'ended_at',
            'created_at',
        )

    ANT_MEDIA_STATUS_MAP = {
        'broadcasting': LiveStream.STATUS_LIVE,
        'finished': LiveStream.STATUS_ENDED,
    }

    def to_representation(self, instance):
        instance = self._sync_status_from_ant_media(instance)
        return super().to_representation(instance)

    def get_rtmp_url(self, obj):
        if not settings.ANT_MEDIA_RTMP_BASE:
            return None
        return settings.ANT_MEDIA_RTMP_BASE

    def get_playback_url(self, obj):
        playback_base = settings.ANT_MEDIA_PLAYBACK_BASE
        if not playback_base and settings.ANT_MEDIA_BASE_URL:
            playback_base = f"{settings.ANT_MEDIA_BASE_URL}/{settings.ANT_MEDIA_APP_NAME}/streams"
        if not playback_base:
            return None
        return f"{playback_base}/{obj.stream_key}.m3u8"

    def get_thumbnail_url(self, obj):
        return self._build_preview_image_url(obj)

    def get_preview_image_url(self, obj):
        return self._build_preview_image_url(obj)

    def get_snapshot_url(self, obj):
        return self._build_preview_image_url(obj)

    def get_status_source(self, obj):
        return getattr(obj, '_status_source', 'django_control')

    def get_status(self, obj):
        ant_media_status = getattr(obj, '_ant_media_status', None)
        if ant_media_status is not None:
            if ant_media_status == 'broadcasting':
                return LiveStream.STATUS_LIVE
            if ant_media_status == 'finished':
                return LiveStream.STATUS_ENDED
            return 'waiting_for_signal'

        if obj.status == LiveStream.STATUS_LIVE:
            return LiveStream.STATUS_LIVE
        if obj.status == LiveStream.STATUS_ENDED:
            return LiveStream.STATUS_ENDED
        return 'ready'

    def _sync_status_from_ant_media(self, obj):
        if getattr(obj, '_ant_media_sync_attempted', False):
            return obj

        obj._ant_media_sync_attempted = True
        obj._status_source = 'django_control'

        if not settings.ANT_MEDIA_SYNC_STATUS:
            return obj
        if not settings.ANT_MEDIA_BASE_URL or not settings.ANT_MEDIA_REST_APP_NAME:
            return obj

        stream_status = self._fetch_ant_media_status(obj.stream_key)
        if stream_status is None:
            return obj

        obj._status_source = 'ant_media'
        obj._ant_media_status = stream_status
        mapped_status = self.ANT_MEDIA_STATUS_MAP.get(stream_status)
        if not mapped_status:
            return obj
        if obj.status != mapped_status:
            obj.status = mapped_status
            obj.save(update_fields=['status'])
        return obj

    def _fetch_ant_media_status(self, stream_key):
        endpoint = (
            f"{settings.ANT_MEDIA_BASE_URL}/"
            f"{settings.ANT_MEDIA_REST_APP_NAME}/rest/v2/broadcasts/{stream_key}"
        )
        try:
            with urllib_request.urlopen(endpoint, timeout=2) as response:
                payload = json.loads(response.read().decode('utf-8'))
        except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload.get('status')

    def _build_preview_image_url(self, obj):
        if not settings.ANT_MEDIA_PREVIEW_BASE:
            return None
        return f"{settings.ANT_MEDIA_PREVIEW_BASE}/{obj.stream_key}.png"


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
