from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.models import (
    Category,
    ChannelSubscription,
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


class EngagementUserSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='display_name', read_only=True)

    class Meta:
        model = User
        fields = ('id', 'name', 'subscriber_count')
        read_only_fields = fields


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


class VideoInteractionSummarySerializer(serializers.Serializer):
    video_id = serializers.IntegerField(source='id', read_only=True)
    like_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    channel = EngagementUserSerializer(source='owner', read_only=True)
    is_liked = serializers.SerializerMethodField()
    is_subscribed = serializers.SerializerMethodField()

    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        prefetched = getattr(obj, 'is_liked_value', None)
        if prefetched is not None:
            return bool(prefetched)
        return VideoLike.objects.filter(video=obj, user=request.user).exists()

    def get_is_subscribed(self, obj):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        prefetched = getattr(obj, 'is_subscribed_value', None)
        if prefetched is not None:
            return bool(prefetched)
        return ChannelSubscription.objects.filter(channel=obj.owner, subscriber=request.user).exists()


class VideoCommentSerializer(serializers.ModelSerializer):
    author = EngagementUserSerializer(read_only=True)
    like_count = serializers.SerializerMethodField()

    class Meta:
        model = VideoComment
        fields = ('id', 'video', 'author', 'content', 'like_count', 'created_at', 'updated_at')
        read_only_fields = fields

    def get_like_count(self, obj):
        prefetched = getattr(obj, 'like_count', None)
        if prefetched is not None:
            return prefetched
        return obj.likes.count()


class VideoCommentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VideoComment
        fields = ('content',)


class VideoMetadataSerializer(VideoSerializer):
    class Meta(VideoSerializer.Meta):
        read_only_fields = (
            'id',
            'owner_id',
            'owner_name',
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
