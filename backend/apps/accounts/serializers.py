import json

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.constants import BLOCKCHAIN_NAME, LEGACY_CHAIN_CURRENCY_CODE, TOKEN_NAME, TOKEN_PEG, TOKEN_SYMBOL
from apps.accounts.models import (
    BillingPlan,
    BillingSubscription,
    ManualMembershipPayment,
    MembershipPlan,
    PaymentAssetRate,
    Category,
    ChannelSubscription,
    GiftTransaction,
    DramaSeries,
    LiveChatMessage,
    LiveChatRoom,
    LiveStream,
    LiveStreamProduct,
    PaymentOrder,
    Product,
    ProductCategory,
    ProductOrder,
    ProductRefundRequest,
    ProductShipment,
    PlatformAssetLedger,
    SavedProduct,
    SellerApplication,
    SellerPayoutAddress,
    SellerStore,
    SellerPayout,
    ShopBanner,
    UserAssetBalance,
    UserAssetTransaction,
    StreamPaymentMethod,
    UserShippingAddress,
    Video,
    VideoComment,
    VideoLike,
    UserMembership,
)
from apps.accounts.services import AntMediaLiveAdapter, ProductOrderService, get_membership_payment_asset_rate

User = get_user_model()
LEGACY_CATEGORY_SLUG_ALIASES = {
    'tech': 'technology',
}


def public_active_videos_for_user(user):
    return Video.objects.filter(
        owner=user,
        visibility=Video.VISIBILITY_PUBLIC,
        status=Video.STATUS_ACTIVE,
    )


def published_dramas_for_user(user):
    return DramaSeries.objects.filter(
        owner=user,
        is_active=True,
        status=DramaSeries.STATUS_PUBLISHED,
    )


def non_private_lives_for_user(user):
    return LiveStream.objects.filter(owner=user).exclude(visibility=LiveStream.VISIBILITY_PRIVATE)


def content_aggregate_summary(user):
    public_videos = public_active_videos_for_user(user)
    published_dramas = published_dramas_for_user(user)
    non_private_lives = non_private_lives_for_user(user)

    video_count = public_videos.count()
    drama_count = published_dramas.count()
    live_count = non_private_lives.count()
    video_total_views = public_videos.aggregate(total=Count('views')).get('total') or 0
    drama_total_views = published_dramas.aggregate(total=Sum('view_count')).get('total') or 0
    live_total_views = 0
    video_total_likes = VideoLike.objects.filter(video__in=public_videos).count()
    drama_total_likes = 0
    live_total_likes = 0
    total_views = video_total_views + drama_total_views + live_total_views
    total_likes = video_total_likes + drama_total_likes + live_total_likes

    return {
        'video_count': video_count,
        'drama_count': drama_count,
        'live_count': live_count,
        'video_total_views': video_total_views,
        'drama_total_views': drama_total_views,
        'live_total_views': live_total_views,
        'total_views': total_views,
        'view_count': total_views,
        'video_total_likes': video_total_likes,
        'drama_total_likes': drama_total_likes,
        'live_total_likes': live_total_likes,
        'total_likes': total_likes,
        'like_count': total_likes,
    }


class OptionalSlugRelatedField(serializers.SlugRelatedField):
    def to_internal_value(self, data):
        if data in (None, ''):
            return None
        data = LEGACY_CATEGORY_SLUG_ALIASES.get(data, data)
        return super().to_internal_value(data)


class UserSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)
    avatar_url = serializers.SerializerMethodField()
    is_admin = serializers.SerializerMethodField()
    linked_wallet_id = serializers.CharField(read_only=True, allow_blank=True)
    primary_user_address = serializers.CharField(read_only=True, allow_blank=True)
    wallet_link_status = serializers.CharField(read_only=True, allow_blank=True)
    linked_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        model = User
        fields = (
            'id',
            'email',
            'display_name',
            'first_name',
            'last_name',
            'avatar',
            'avatar_url',
            'is_creator',
            'is_admin',
            'linked_wallet_id',
            'primary_user_address',
            'wallet_link_status',
            'linked_at',
        )
        read_only_fields = ('id',)

    def get_avatar_url(self, obj):
        request = self.context.get('request')
        if not obj.avatar:
            return None
        if request is None:
            return obj.avatar.url
        return request.build_absolute_uri(obj.avatar.url)

    def get_is_admin(self, obj):
        return bool(obj.is_staff or obj.is_superuser)


class AccountProfileSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(required=False, allow_blank=True)
    avatar_url = serializers.SerializerMethodField()
    avatar_clear = serializers.BooleanField(write_only=True, required=False, default=False)
    id = serializers.IntegerField(read_only=True)
    email = serializers.EmailField(read_only=True)
    is_creator = serializers.BooleanField(read_only=True)
    is_seller = serializers.SerializerMethodField()
    is_admin = serializers.SerializerMethodField()
    can_create_live = serializers.SerializerMethodField()
    can_manage_store = serializers.SerializerMethodField()
    can_accept_payments = serializers.SerializerMethodField()
    linked_wallet_id = serializers.CharField(required=False, allow_blank=True, max_length=128)
    primary_user_address = serializers.CharField(required=False, allow_blank=True, max_length=128)
    wallet_link_status = serializers.ChoiceField(required=False, allow_blank=True, choices=User.WALLET_LINK_STATUS_CHOICES)
    seller_store = serializers.SerializerMethodField()
    counts = serializers.SerializerMethodField()
    follower_count = serializers.SerializerMethodField()
    subscriber_count = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    total_likes = serializers.SerializerMethodField()
    gift_count = serializers.SerializerMethodField()
    total_gifts = serializers.SerializerMethodField()
    video_count = serializers.SerializerMethodField()
    drama_count = serializers.SerializerMethodField()
    live_count = serializers.SerializerMethodField()
    total_videos = serializers.SerializerMethodField()
    video_total_views = serializers.SerializerMethodField()
    drama_total_views = serializers.SerializerMethodField()
    live_total_views = serializers.SerializerMethodField()
    total_views = serializers.SerializerMethodField()
    view_count = serializers.SerializerMethodField()
    video_total_likes = serializers.SerializerMethodField()
    drama_total_likes = serializers.SerializerMethodField()
    live_total_likes = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id',
            'email',
            'display_name',
            'first_name',
            'last_name',
            'avatar',
            'avatar_clear',
            'avatar_url',
            'bio',
            'is_creator',
            'is_seller',
            'is_admin',
            'can_create_live',
            'can_manage_store',
            'can_accept_payments',
            'linked_wallet_id',
            'primary_user_address',
            'wallet_link_status',
            'linked_at',
            'seller_store',
            'follower_count',
            'subscriber_count',
            'like_count',
            'total_likes',
            'gift_count',
            'total_gifts',
            'video_count',
            'drama_count',
            'live_count',
            'total_videos',
            'video_total_views',
            'drama_total_views',
            'live_total_views',
            'total_views',
            'view_count',
            'video_total_likes',
            'drama_total_likes',
            'live_total_likes',
            'counts',
        )
        read_only_fields = (
            'id',
            'email',
            'is_creator',
            'is_seller',
            'is_admin',
            'can_create_live',
            'can_manage_store',
            'can_accept_payments',
            'linked_at',
            'seller_store',
            'follower_count',
            'subscriber_count',
            'like_count',
            'total_likes',
            'gift_count',
            'total_gifts',
            'video_count',
            'drama_count',
            'live_count',
            'total_videos',
            'video_total_views',
            'drama_total_views',
            'live_total_views',
            'total_views',
            'view_count',
            'video_total_likes',
            'drama_total_likes',
            'live_total_likes',
            'counts',
        )

    def get_avatar_url(self, obj):
        request = self.context.get('request')
        if not obj.avatar:
            return None
        if request is None:
            return obj.avatar.url
        return request.build_absolute_uri(obj.avatar.url)

    def get_is_seller(self, obj):
        return self._summary(obj)['is_seller']

    def get_is_admin(self, obj):
        return self._summary(obj)['is_admin']

    def get_can_create_live(self, obj):
        return self._summary(obj)['can_create_live']

    def get_can_manage_store(self, obj):
        return self._summary(obj)['can_manage_store']

    def get_can_accept_payments(self, obj):
        return self._summary(obj)['can_accept_payments']

    def get_seller_store(self, obj):
        return self._summary(obj)['seller_store']

    def get_counts(self, obj):
        return self._summary(obj)['counts']

    def get_follower_count(self, obj):
        return self._summary(obj)['follower_count']

    def get_subscriber_count(self, obj):
        return self._summary(obj)['follower_count']

    def get_like_count(self, obj):
        return self._summary(obj)['like_count']

    def get_total_likes(self, obj):
        return self._summary(obj)['total_likes']

    def get_video_total_likes(self, obj):
        return self._summary(obj)['video_total_likes']

    def get_drama_total_likes(self, obj):
        return self._summary(obj)['drama_total_likes']

    def get_live_total_likes(self, obj):
        return self._summary(obj)['live_total_likes']

    def get_gift_count(self, obj):
        return self._summary(obj)['gift_count']

    def get_total_gifts(self, obj):
        return self._summary(obj)['gift_count']

    def get_video_count(self, obj):
        return self._summary(obj)['video_count']

    def get_drama_count(self, obj):
        return self._summary(obj)['drama_count']

    def get_live_count(self, obj):
        return self._summary(obj)['live_count']

    def get_total_videos(self, obj):
        return self._summary(obj)['video_count']

    def get_video_total_views(self, obj):
        return self._summary(obj)['video_total_views']

    def get_drama_total_views(self, obj):
        return self._summary(obj)['drama_total_views']

    def get_live_total_views(self, obj):
        return self._summary(obj)['live_total_views']

    def get_total_views(self, obj):
        return self._summary(obj)['total_views']

    def get_view_count(self, obj):
        return self._summary(obj)['view_count']

    def _summary(self, obj):
        summary = getattr(obj, '_account_profile_summary_cache', None)
        if summary is not None:
            return summary

        seller_store = SellerStore.objects.filter(owner=obj).only('id', 'name', 'slug', 'is_active').first()
        content_summary = content_aggregate_summary(obj)
        video_count = content_summary['video_count']
        follower_count = ChannelSubscription.objects.filter(channel=obj).count()
        gift_count = GiftTransaction.objects.filter(receiver=obj).count()
        product_count = Product.objects.filter(store__owner=obj).count()
        payment_method_count = StreamPaymentMethod.objects.filter(stream__owner=obj).count()
        summary = {
            'follower_count': follower_count,
            'like_count': content_summary['total_likes'],
            'total_likes': content_summary['total_likes'],
            'gift_count': gift_count,
            **content_summary,
            'is_seller': seller_store is not None,
            'is_admin': bool(obj.is_staff or obj.is_superuser),
            'can_create_live': bool(obj.is_creator),
            'can_manage_store': seller_store is not None,
            'can_accept_payments': bool(obj.is_creator or seller_store is not None),
            'seller_store': (
                {
                    'id': seller_store.id,
                    'name': seller_store.name,
                    'slug': seller_store.slug,
                    'is_active': seller_store.is_active,
                }
                if seller_store is not None else None
            ),
            'counts': {
                'videos': video_count,
                'followers': follower_count,
                'subscribers': follower_count,
                'likes': content_summary['total_likes'],
                'gifts': gift_count,
                'live_streams': content_summary['live_count'],
                'products': product_count,
                'payment_methods': payment_method_count,
                'orders': PaymentOrder.objects.filter(user=obj).count(),
            },
        }
        obj._account_profile_summary_cache = summary
        return summary

    def update(self, instance, validated_data):
        avatar_clear = bool(validated_data.pop('avatar_clear', False))
        display_name = validated_data.pop('display_name', None)

        if display_name is not None:
            normalized_name = display_name.strip()
            if not normalized_name:
                instance.first_name = ''
                instance.last_name = ''
            else:
                parts = normalized_name.split(None, 1)
                instance.first_name = parts[0]
                instance.last_name = parts[1] if len(parts) > 1 else ''

        for field in (
            'first_name',
            'last_name',
            'bio',
            'linked_wallet_id',
            'primary_user_address',
            'wallet_link_status',
        ):
            if field in validated_data:
                setattr(instance, field, validated_data[field])

        if {'linked_wallet_id', 'primary_user_address', 'wallet_link_status'} & set(validated_data.keys()):
            if instance.linked_wallet_id or instance.primary_user_address or instance.wallet_link_status:
                instance.linked_at = instance.linked_at or timezone.now()
            else:
                instance.linked_at = None

        if 'avatar' in validated_data:
            instance.avatar = validated_data['avatar']
        if avatar_clear and instance.avatar:
            instance.avatar.delete(save=False)
            instance.avatar = ''

        instance.save()
        return instance


class PublicCreatorSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()
    subscriber_count = serializers.SerializerMethodField()
    follower_count = serializers.SerializerMethodField()
    video_count = serializers.SerializerMethodField()
    drama_count = serializers.SerializerMethodField()
    live_count = serializers.SerializerMethodField()
    video_total_views = serializers.SerializerMethodField()
    drama_total_views = serializers.SerializerMethodField()
    live_total_views = serializers.SerializerMethodField()
    total_views = serializers.SerializerMethodField()
    view_count = serializers.SerializerMethodField()
    video_total_likes = serializers.SerializerMethodField()
    drama_total_likes = serializers.SerializerMethodField()
    live_total_likes = serializers.SerializerMethodField()
    like_count = serializers.SerializerMethodField()
    total_likes = serializers.SerializerMethodField()
    gift_count = serializers.SerializerMethodField()
    gift_amount_total = serializers.SerializerMethodField()
    viewer_is_following = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id',
            'display_name',
            'avatar_url',
            'bio',
            'is_creator',
            'subscriber_count',
            'follower_count',
            'video_count',
            'drama_count',
            'live_count',
            'video_total_views',
            'drama_total_views',
            'live_total_views',
            'total_views',
            'view_count',
            'video_total_likes',
            'drama_total_likes',
            'live_total_likes',
            'like_count',
            'total_likes',
            'gift_count',
            'gift_amount_total',
            'viewer_is_following',
        )

    def get_avatar_url(self, obj):
        request = self.context.get('request')
        if not obj.avatar:
            return None
        if request is None:
            return obj.avatar.url
        return request.build_absolute_uri(obj.avatar.url)

    def get_subscriber_count(self, obj):
        return ChannelSubscription.objects.filter(channel=obj).count()

    def get_follower_count(self, obj):
        return self.get_subscriber_count(obj)

    def _content_summary(self, obj):
        summary = getattr(obj, '_public_creator_content_summary_cache', None)
        if summary is None:
            summary = content_aggregate_summary(obj)
            obj._public_creator_content_summary_cache = summary
        return summary

    def get_video_count(self, obj):
        return self._content_summary(obj)['video_count']

    def get_drama_count(self, obj):
        return self._content_summary(obj)['drama_count']

    def get_live_count(self, obj):
        return self._content_summary(obj)['live_count']

    def get_video_total_views(self, obj):
        return self._content_summary(obj)['video_total_views']

    def get_drama_total_views(self, obj):
        return self._content_summary(obj)['drama_total_views']

    def get_live_total_views(self, obj):
        return self._content_summary(obj)['live_total_views']

    def get_total_views(self, obj):
        return self._content_summary(obj)['total_views']

    def get_view_count(self, obj):
        return self._content_summary(obj)['view_count']

    def get_video_total_likes(self, obj):
        return self._content_summary(obj)['video_total_likes']

    def get_drama_total_likes(self, obj):
        return self._content_summary(obj)['drama_total_likes']

    def get_live_total_likes(self, obj):
        return self._content_summary(obj)['live_total_likes']

    def get_like_count(self, obj):
        return self._content_summary(obj)['like_count']

    def get_total_likes(self, obj):
        return self._content_summary(obj)['total_likes']

    def get_gift_count(self, obj):
        return GiftTransaction.objects.filter(
            receiver=obj,
            target_type=GiftTransaction.TARGET_VIDEO,
            video__owner=obj,
        ).count()

    def get_gift_amount_total(self, obj):
        aggregate = GiftTransaction.objects.filter(
            receiver=obj,
            target_type=GiftTransaction.TARGET_VIDEO,
            video__owner=obj,
        ).aggregate(total=Sum('amount'))
        return aggregate.get('total') or 0

    def get_viewer_is_following(self, obj):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        return ChannelSubscription.objects.filter(channel=obj, subscriber=request.user).exists()


class PublicUserListItemSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    nickname = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    description = serializers.CharField(source='bio', read_only=True)
    followers_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'nickname',
            'display_name',
            'avatar',
            'avatar_url',
            'bio',
            'description',
            'is_creator',
            'followers_count',
        )

    def _public_display_name(self, obj):
        full_name = f'{obj.first_name} {obj.last_name}'.strip()
        if full_name:
            return full_name
        return f'User {obj.id}'

    def _build_file_url(self, file_field):
        if not file_field:
            return None
        request = self.context.get('request')
        if request is None:
            return file_field.url
        return request.build_absolute_uri(file_field.url)

    def get_username(self, obj):
        return self._public_display_name(obj)

    def get_nickname(self, obj):
        return self._public_display_name(obj)

    def get_display_name(self, obj):
        return self._public_display_name(obj)

    def get_avatar(self, obj):
        return self._build_file_url(obj.avatar)

    def get_avatar_url(self, obj):
        return self.get_avatar(obj)

    def get_followers_count(self, obj):
        return ChannelSubscription.objects.filter(channel=obj).count()


class PublicUserProfileSerializer(serializers.ModelSerializer):
    username = serializers.SerializerMethodField()
    nickname = serializers.SerializerMethodField()
    display_name = serializers.SerializerMethodField()
    avatar = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    description = serializers.CharField(source='bio', read_only=True)
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    contents = serializers.SerializerMethodField()
    posts = serializers.SerializerMethodField()
    works = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id',
            'username',
            'nickname',
            'display_name',
            'avatar',
            'avatar_url',
            'bio',
            'description',
            'is_creator',
            'followers_count',
            'following_count',
            'contents',
            'posts',
            'works',
        )

    def _public_display_name(self, obj):
        full_name = f'{obj.first_name} {obj.last_name}'.strip()
        if full_name:
            return full_name
        return f'User {obj.id}'

    def _build_file_url(self, file_field):
        if not file_field:
            return None
        request = self.context.get('request')
        if request is None:
            return file_field.url
        return request.build_absolute_uri(file_field.url)

    def get_username(self, obj):
        return self._public_display_name(obj)

    def get_nickname(self, obj):
        return self._public_display_name(obj)

    def get_display_name(self, obj):
        return self._public_display_name(obj)

    def get_avatar(self, obj):
        return self._build_file_url(obj.avatar)

    def get_avatar_url(self, obj):
        return self.get_avatar(obj)

    def get_followers_count(self, obj):
        return ChannelSubscription.objects.filter(channel=obj).count()

    def get_following_count(self, obj):
        return ChannelSubscription.objects.filter(subscriber=obj).count()

    def _serialize_public_works(self, obj):
        if hasattr(self, '_public_works_cache') and obj.pk in self._public_works_cache:
            return self._public_works_cache[obj.pk]
        if not hasattr(self, '_public_works_cache'):
            self._public_works_cache = {}
        if not obj.is_creator:
            self._public_works_cache[obj.pk] = []
            return []
        request = self.context.get('request')
        works = []
        videos = Video.objects.filter(
            owner=obj,
            visibility=Video.VISIBILITY_PUBLIC,
            status=Video.STATUS_ACTIVE,
        ).order_by('-created_at', '-id')[:20]
        for video in videos:
            thumbnail_url = None
            if video.thumbnail:
                thumbnail_url = (
                    video.thumbnail.url
                    if request is None
                    else request.build_absolute_uri(video.thumbnail.url)
                )
            works.append(
                {
                    'id': video.id,
                    'type': 'video',
                    'title': video.title,
                    'description': video.description,
                    'thumbnail_url': thumbnail_url,
                    'created_at': video.created_at,
                }
            )
        self._public_works_cache[obj.pk] = works
        return works

    def get_contents(self, obj):
        return self._serialize_public_works(obj)

    def get_posts(self, obj):
        return self.get_contents(obj)

    def get_works(self, obj):
        return self.get_contents(obj)


class AccountPasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError('Current password is incorrect.')
        return value

    def validate_new_password(self, value):
        user = self.context['request'].user
        validate_password(value, user=user)
        return value


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
            'is_creator',
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
    owner_subscriber_count = serializers.IntegerField(source='owner.subscriber_count', read_only=True)
    is_following_owner = serializers.SerializerMethodField()
    creator = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    description_preview = serializers.SerializerMethodField()
    category_name = serializers.CharField(read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)
    like_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    access_type = serializers.ChoiceField(
        choices=[Video.ACCESS_FREE, Video.ACCESS_MEMBERSHIP],
        required=False,
    )
    preview_seconds = serializers.IntegerField(min_value=0, required=False)
    view_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    can_watch = serializers.SerializerMethodField()
    is_locked = serializers.SerializerMethodField()
    lock_reason = serializers.SerializerMethodField()
    category = OptionalSlugRelatedField(
        slug_field='slug',
        queryset=Category.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )
    visibility = serializers.ChoiceField(
        choices=[Video.VISIBILITY_PUBLIC, Video.VISIBILITY_PRIVATE],
        required=False,
    )

    class Meta:
        model = Video
        fields = (
            'id',
            'owner_id',
            'owner_name',
            'owner_avatar_url',
            'owner_subscriber_count',
            'is_following_owner',
            'creator',
            'title',
            'description',
            'description_preview',
            'visibility',
            'category',
            'category_name',
            'category_slug',
            'access_type',
            'preview_seconds',
            'can_watch',
            'is_locked',
            'lock_reason',
            'like_count',
            'comment_count',
            'view_count',
            'share_count',
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
            'owner_subscriber_count',
            'is_following_owner',
            'creator',
            'category_name',
            'category_slug',
            'like_count',
            'comment_count',
            'view_count',
            'share_count',
            'is_liked',
            'file_url',
            'thumbnail_url',
            'can_watch',
            'is_locked',
            'lock_reason',
            'created_at',
        )

    def get_owner_avatar_url(self, obj):
        request = self.context.get('request')
        if not obj.owner.avatar:
            return None
        if request is None:
            return obj.owner.avatar.url
        return request.build_absolute_uri(obj.owner.avatar.url)

    def get_is_following_owner(self, obj):
        request = self.context.get('request')
        if request is None or not getattr(request, 'user', None) or not request.user.is_authenticated:
            return False
        prefetched = getattr(obj, 'is_subscribed_value', None)
        if prefetched is not None:
            return bool(prefetched)
        return ChannelSubscription.objects.filter(channel=obj.owner, subscriber=request.user).exists()

    def get_creator(self, obj):
        return {
            'id': obj.owner_id,
            'name': obj.owner.display_name,
            'avatar_url': self.get_owner_avatar_url(obj),
            'is_creator': obj.owner.is_creator,
            'is_following': self.get_is_following_owner(obj),
            'subscriber_count': obj.owner.subscriber_count,
        }

    def get_file_url(self, obj):
        if not self._can_watch(obj):
            return None
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

    def get_can_watch(self, obj):
        return self._can_watch(obj)

    def get_is_locked(self, obj):
        return not self._can_watch(obj)

    def get_lock_reason(self, obj):
        if self._can_watch(obj):
            return None
        if obj.access_type == Video.ACCESS_MEMBERSHIP:
            return 'membership_required'
        return None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if self.context.get('mask_locked_file_fields', False) and not self._can_watch(instance):
            data['file'] = None
            data['file_url'] = None
        return data

    def _build_absolute_file_url(self, field_file):
        request = self.context.get('request')
        if not field_file:
            return None
        if request is None:
            return field_file.url
        return request.build_absolute_uri(field_file.url)

    def _can_watch(self, obj):
        if obj.access_type == Video.ACCESS_FREE:
            return True
        return self._viewer_has_active_membership()

    def _viewer_has_active_membership(self):
        cached = getattr(self, '_has_active_membership_cache', None)
        if cached is not None:
            return cached
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request is not None else None
        if user is None or not user.is_authenticated:
            self._has_active_membership_cache = False
            return False
        now = timezone.now()
        has_membership = UserMembership.objects.filter(
            user=user,
            status=UserMembership.STATUS_ACTIVE,
            starts_at__lte=now,
            ends_at__gt=now,
        ).exists()
        self._has_active_membership_cache = has_membership
        return has_membership




class LiveStreamSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    owner_name = serializers.CharField(source='owner.display_name', read_only=True)
    owner_avatar_url = serializers.SerializerMethodField()
    creator = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    category = OptionalSlugRelatedField(
        slug_field='slug',
        queryset=Category.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )
    rtmp_url = serializers.SerializerMethodField()
    playback_url = serializers.SerializerMethodField()
    watch_url = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    preview_image_url = serializers.SerializerMethodField()
    snapshot_url = serializers.SerializerMethodField()
    status_source = serializers.SerializerMethodField()
    viewer_count = serializers.SerializerMethodField()
    django_status = serializers.SerializerMethodField()
    effective_status = serializers.SerializerMethodField()
    raw_ant_media_status = serializers.SerializerMethodField()
    ant_media_status = serializers.SerializerMethodField()
    no_signal_count = serializers.SerializerMethodField()
    should_end = serializers.SerializerMethodField()
    sync_ok = serializers.SerializerMethodField()
    sync_error = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()
    can_start = serializers.SerializerMethodField()
    can_end = serializers.SerializerMethodField()
    thumbnail_capture_status = serializers.CharField(read_only=True)
    thumbnail_captured_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = LiveStream
        fields = (
            'id',
            'owner_id',
            'owner_name',
            'owner_avatar_url',
            'creator',
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
            'ant_media_status',
            'no_signal_count',
            'should_end',
            'rtmp_url',
            'playback_url',
            'watch_url',
            'thumbnail_url',
            'preview_image_url',
            'snapshot_url',
            'thumbnail_capture_status',
            'thumbnail_captured_at',
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
            'owner_avatar_url',
            'creator',
            'category_name',
            'status',
            'django_status',
            'effective_status',
            'status_source',
            'raw_ant_media_status',
            'ant_media_status',
            'no_signal_count',
            'should_end',
            'rtmp_url',
            'playback_url',
            'watch_url',
            'thumbnail_url',
            'preview_image_url',
            'snapshot_url',
            'thumbnail_capture_status',
            'thumbnail_captured_at',
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

    def get_owner_avatar_url(self, obj):
        request = self.context.get('request')
        if not obj.owner.avatar:
            return None
        if request is None:
            return obj.owner.avatar.url
        return request.build_absolute_uri(obj.owner.avatar.url)

    def get_creator(self, obj):
        return {
            'id': obj.owner_id,
            'name': obj.owner.display_name,
            'avatar_url': self.get_owner_avatar_url(obj),
        }

    def get_playback_url(self, obj):
        return self._normalized(obj).get('playback_url')

    def get_watch_url(self, obj):
        relative_url = f'/live/{obj.id}'
        request = self.context.get('request')
        if request is None:
            return relative_url
        return request.build_absolute_uri(relative_url)

    def get_thumbnail_url(self, obj):
        request = self.context.get('request')
        if getattr(obj, 'thumbnail', None):
            if request is None:
                return obj.thumbnail.url
            return request.build_absolute_uri(obj.thumbnail.url)
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
        normalized_count = self._normalized(obj).get('viewer_count') or 0
        return max(normalized_count, obj.viewer_count or 0)

    def get_django_status(self, obj):
        return self._normalized(obj).get('django_status')

    def get_effective_status(self, obj):
        return self._normalized(obj).get('effective_status')

    def get_raw_ant_media_status(self, obj):
        return self._normalized(obj).get('raw_ant_media_status')

    def get_ant_media_status(self, obj):
        return self._normalized(obj).get('ant_media_status')

    def get_no_signal_count(self, obj):
        return self._normalized(obj).get('no_signal_count')

    def get_should_end(self, obj):
        return self._normalized(obj).get('should_end')

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


class SellerApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SellerApplication
        fields = (
            'id',
            'store_name',
            'business_type',
            'business_description',
            'contact_phone',
            'contact_email',
            'business_license_url',
            'status',
            'rejection_reason',
            'submitted_at',
            'reviewed_at',
        )
        read_only_fields = ('id', 'status', 'rejection_reason', 'submitted_at', 'reviewed_at')

    def validate(self, attrs):
        business_type = attrs.get('business_type')
        business_license_url = attrs.get('business_license_url')
        if business_type == SellerApplication.BUSINESS_TYPE_COMPANY and not business_license_url:
            raise serializers.ValidationError({
                'business_license_url': 'Business license URL is required for company applications.'
            })
        return attrs


class AdminSellerApplicationSerializer(SellerApplicationSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    user_email = serializers.EmailField(source='user.email', read_only=True)
    reviewed_by_id = serializers.IntegerField(source='reviewed_by.id', read_only=True, allow_null=True)

    class Meta(SellerApplicationSerializer.Meta):
        fields = SellerApplicationSerializer.Meta.fields + (
            'user_id',
            'user_email',
            'reviewed_by_id',
        )


class SellerApplicationRejectSerializer(serializers.Serializer):
    rejection_reason = serializers.CharField(allow_blank=False, trim_whitespace=True)


class SellerStoreSerializer(serializers.ModelSerializer):
    owner_id = serializers.IntegerField(source='owner.id', read_only=True)
    owner_name = serializers.CharField(source='owner.display_name', read_only=True)
    logo_url = serializers.SerializerMethodField()
    banner_url = serializers.SerializerMethodField()

    class Meta:
        model = SellerStore
        fields = (
            'id',
            'owner_id',
            'owner_name',
            'name',
            'slug',
            'description',
            'logo',
            'logo_url',
            'banner',
            'banner_url',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'owner_id',
            'owner_name',
            'created_at',
            'updated_at',
        )

    def get_logo_url(self, obj):
        return self._build_absolute_file_url(obj.logo)

    def get_banner_url(self, obj):
        return self._build_absolute_file_url(obj.banner)

    def _build_absolute_file_url(self, field_file):
        request = self.context.get('request')
        if not field_file:
            return None
        if request is None:
            return field_file.url
        return request.build_absolute_uri(field_file.url)


class ProductSerializer(serializers.ModelSerializer):
    store_id = serializers.IntegerField(source='store.id', read_only=True)
    name = serializers.CharField(source='title', read_only=True)
    category = serializers.SerializerMethodField()
    category_id = serializers.PrimaryKeyRelatedField(
        source='category',
        queryset=ProductCategory.objects.filter(is_active=True),
        required=False,
        allow_null=True,
    )
    cover_image_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    price = serializers.DecimalField(source='price_amount', max_digits=12, decimal_places=2, read_only=True)
    original_price = serializers.SerializerMethodField()
    badge = serializers.SerializerMethodField()
    stock = serializers.IntegerField(source='stock_quantity', read_only=True)
    sold_count = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            'id',
            'store_id',
            'title',
            'name',
            'slug',
            'category',
            'category_id',
            'description',
            'cover_image',
            'cover_image_url',
            'thumbnail_url',
            'price_amount',
            'price',
            'original_price',
            'price_currency',
            'meow_points_price',
            'meow_credit_price',
            'stock_quantity',
            'stock',
            'sold_count',
            'badge',
            'is_active',
            'status',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'store_id',
            'name',
            'category',
            'cover_image_url',
            'thumbnail_url',
            'price',
            'original_price',
            'stock',
            'sold_count',
            'badge',
            'is_active',
            'created_at',
            'updated_at',
        )

    def to_internal_value(self, data):
        if 'category' in data and 'category_id' not in data and not isinstance(data.get('category'), dict):
            data = data.copy()
            data['category_id'] = data.get('category')
        return super().to_internal_value(data)

    def get_category(self, obj):
        if obj.category is None:
            return None
        return {
            'id': obj.category.id,
            'name': obj.category.name,
            'slug': obj.category.slug,
        }

    def get_cover_image_url(self, obj):
        request = self.context.get('request')
        if not obj.cover_image:
            return None
        if request is None:
            return obj.cover_image.url
        return request.build_absolute_uri(obj.cover_image.url)

    def get_thumbnail_url(self, obj):
        return self.get_cover_image_url(obj)

    def get_original_price(self, obj):
        return None

    def get_badge(self, obj):
        return None

    def get_sold_count(self, obj):
        return 0

    def get_is_active(self, obj):
        return obj.status == Product.STATUS_ACTIVE


class ShopBannerSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShopBanner
        fields = ('id', 'image_url', 'title', 'subtitle', 'target_url')
        read_only_fields = fields


class ProductCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductCategory
        fields = ('id', 'name', 'slug')
        read_only_fields = fields


class ShopProductListSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='title', read_only=True)
    price = serializers.DecimalField(source='price_amount', max_digits=12, decimal_places=2, read_only=True)
    original_price = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    badge = serializers.SerializerMethodField()
    description = serializers.SerializerMethodField()
    images = serializers.SerializerMethodField()
    specs = serializers.SerializerMethodField()
    category = ProductCategorySerializer(read_only=True)
    sold_count = serializers.SerializerMethodField()
    stock = serializers.IntegerField(source='stock_quantity', read_only=True)
    meow_points_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)
    meow_credit_price = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True, allow_null=True)

    class Meta:
        model = Product
        fields = (
            'id', 'name', 'price', 'original_price', 'thumbnail_url', 'badge',
            'sold_count', 'stock', 'description', 'images', 'specs', 'category',
            'meow_points_price', 'meow_credit_price',
        )
        read_only_fields = fields

    def get_original_price(self, obj):
        return None

    def get_thumbnail_url(self, obj):
        request = self.context.get('request')
        if not obj.cover_image:
            return None
        if request is None:
            return obj.cover_image.url
        return request.build_absolute_uri(obj.cover_image.url)

    def get_badge(self, obj):
        return None

    def get_sold_count(self, obj):
        return 0

    def get_description(self, obj):
        return obj.description or None

    def get_images(self, obj):
        return []

    def get_specs(self, obj):
        return []


class SavedProductSerializer(serializers.ModelSerializer):
    product = serializers.SerializerMethodField()

    class Meta:
        model = SavedProduct
        fields = ('id', 'product', 'created_at')
        read_only_fields = fields

    def get_product(self, obj):
        return ShopProductListSerializer(obj.product, context=self.context).data


class AddSavedProductSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()

    def validate(self, attrs):
        product = Product.objects.select_related('store', 'category').filter(pk=attrs['product_id']).first()
        if product is None:
            raise serializers.ValidationError({'product_id': ['Product not found.']})
        if product.status != Product.STATUS_ACTIVE:
            raise serializers.ValidationError({'product_id': ['Product is not active.']})
        if not product.store.is_active:
            raise serializers.ValidationError({'product_id': ['Seller store is inactive.']})
        attrs['product'] = product
        return attrs


class LiveStreamProductListingSerializer(serializers.ModelSerializer):
    binding_id = serializers.IntegerField(source='id', read_only=True)
    product = serializers.SerializerMethodField()

    class Meta:
        model = LiveStreamProduct
        fields = (
            'binding_id',
            'sort_order',
            'is_pinned',
            'product',
        )
        read_only_fields = fields

    def get_product(self, obj):
        request = self.context.get('request')
        product = obj.product
        cover_image_url = None
        if product.cover_image:
            cover_image_url = product.cover_image.url if request is None else request.build_absolute_uri(product.cover_image.url)
        return {
            'id': product.id,
            'title': product.title,
            'description': product.description,
            'cover_image_url': cover_image_url,
            'price_amount': str(product.price_amount),
            'price_currency': product.price_currency,
            'store': {
                'id': product.store.id,
                'name': product.store.name,
                'slug': product.store.slug,
            },
        }


class LiveStreamProductManageCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    sort_order = serializers.IntegerField(min_value=0, required=False, default=0)
    is_pinned = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)
    start_at = serializers.DateTimeField(required=False, allow_null=True)
    end_at = serializers.DateTimeField(required=False, allow_null=True)


class LiveStreamProductManageUpdateSerializer(serializers.Serializer):
    sort_order = serializers.IntegerField(min_value=0, required=False)
    is_pinned = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    start_at = serializers.DateTimeField(required=False, allow_null=True)
    end_at = serializers.DateTimeField(required=False, allow_null=True)


class LiveChatMessageCreateSerializer(serializers.Serializer):
    message_type = serializers.ChoiceField(choices=LiveChatMessage.MESSAGE_TYPE_CHOICES, required=False, default=LiveChatMessage.TYPE_TEXT)
    content = serializers.CharField(required=False, allow_blank=True, max_length=1000)
    reply_to_id = serializers.IntegerField(required=False)
    product_id = serializers.IntegerField(required=False)

    def validate(self, attrs):
        message_type = attrs.get('message_type', LiveChatMessage.TYPE_TEXT)
        if message_type == LiveChatMessage.TYPE_TEXT:
            content = (attrs.get('content') or '').strip()
            if not content:
                raise serializers.ValidationError({'content': ['Text messages cannot be empty.']})
            attrs['content'] = content
        if message_type == LiveChatMessage.TYPE_PRODUCT and not attrs.get('product_id'):
            raise serializers.ValidationError({'product_id': ['This field is required for product messages.']})
        return attrs


class LiveChatMessageSerializer(serializers.ModelSerializer):
    live_id = serializers.IntegerField(source='room.stream_id', read_only=True)
    user = serializers.SerializerMethodField()
    product = serializers.SerializerMethodField()
    message = serializers.CharField(source='content', read_only=True)

    class Meta:
        model = LiveChatMessage
        fields = (
            'id',
            'live_id',
            'type',
            'payload',
            'message_type',
            'message',
            'content',
            'created_at',
            'is_pinned',
            'user',
            'product',
        )
        read_only_fields = fields

    def get_user(self, obj):
        if obj.user is None:
            return None
        return {
            'id': obj.user.id,
            'name': obj.user.display_name,
            'avatar_url': None,
        }

    def get_product(self, obj):
        if obj.message_type != LiveChatMessage.TYPE_PRODUCT or obj.product is None:
            return None
        request = self.context.get('request')
        cover_image_url = None
        if obj.product.cover_image:
            cover_image_url = obj.product.cover_image.url if request is None else request.build_absolute_uri(obj.product.cover_image.url)
        return {
            'id': obj.product.id,
            'title': obj.product.title,
            'description': obj.product.description,
            'cover_image_url': cover_image_url,
            'price_amount': str(obj.product.price_amount),
            'price_currency': obj.product.price_currency,
            'store': {
                'id': obj.product.store.id,
                'name': obj.product.store.name,
                'slug': obj.product.store.slug,
            },
        }


class StreamPaymentMethodSerializer(serializers.ModelSerializer):
    qr_image_url = serializers.SerializerMethodField()

    class Meta:
        model = StreamPaymentMethod
        fields = (
            'id',
            'method_type',
            'title',
            'qr_image',
            'qr_image_url',
            'qr_text',
            'wallet_address',
            'sort_order',
            'is_active',
        )
        read_only_fields = ('id', 'qr_image_url')

    def get_qr_image_url(self, obj):
        request = self.context.get('request')
        if not obj.qr_image:
            return None
        if request is None:
            return obj.qr_image.url
        return request.build_absolute_uri(obj.qr_image.url)


class PaymentOrderCreateSerializer(serializers.ModelSerializer):
    client_request_id = serializers.CharField(required=False, allow_blank=True, max_length=128)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=128, write_only=True)

    class Meta:
        model = PaymentOrder
        fields = (
            'id',
            'product',
            'payment_method',
            'order_type',
            'amount',
            'currency',
            'client_request_id',
            'idempotency_key',
            'external_reference',
            'status',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'status', 'created_at', 'updated_at')

    def validate(self, attrs):
        stream = self.context.get('stream')
        if stream is None:
            raise serializers.ValidationError({'detail': ['Missing stream context.']})

        provided_request_id = (attrs.get('client_request_id') or '').strip()
        provided_idempotency_key = (attrs.get('idempotency_key') or '').strip()
        if provided_request_id and provided_idempotency_key and provided_request_id != provided_idempotency_key:
            raise serializers.ValidationError(
                {'idempotency_key': ['Must match client_request_id when both are provided.']}
            )
        attrs['client_request_id'] = provided_request_id or provided_idempotency_key

        order_type = attrs.get('order_type')
        product = attrs.get('product')
        if order_type == PaymentOrder.TYPE_PRODUCT and not product:
            raise serializers.ValidationError({'product': ['This field is required for product orders.']})

        payment_method = attrs.get('payment_method')
        if payment_method:
            if payment_method.stream_id != stream.id:
                raise serializers.ValidationError(
                    {'payment_method': ['Payment method must belong to the target stream.']}
                )
            if not payment_method.is_active:
                raise serializers.ValidationError({'payment_method': ['Payment method is inactive.']})

        if product:
            if product.status != Product.STATUS_ACTIVE:
                raise serializers.ValidationError({'product': ['Product is not available for purchase.']})
            if not product.store.is_active:
                raise serializers.ValidationError({'product': ['Product store is inactive.']})
            active_binding_exists = LiveStreamProduct.objects.filter(
                stream=stream,
                product=product,
                is_active=True,
            ).exists()
            if not active_binding_exists:
                raise serializers.ValidationError(
                    {'product': ['Product is not active for this live stream.']}
                )
        return attrs


class PaymentOrderSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='user.id', read_only=True, allow_null=True)
    stream_id = serializers.IntegerField(source='stream.id', read_only=True, allow_null=True)
    product_id = serializers.IntegerField(source='product.id', read_only=True, allow_null=True)
    payment_method_id = serializers.IntegerField(source='payment_method.id', read_only=True, allow_null=True)
    wallet_address_id = serializers.IntegerField(source='wallet_address.id', read_only=True, allow_null=True)
    paid_by_id = serializers.IntegerField(source='paid_by.id', read_only=True, allow_null=True)
    currency_display = serializers.SerializerMethodField()

    class Meta:
        model = PaymentOrder
        fields = (
            'id',
            'order_no',
            'user_id',
            'stream_id',
            'product_id',
            'payment_method_id',
            'wallet_address_id',
            'order_type',
            'target_type',
            'target_id',
            'amount',
            'currency',
            'currency_display',
            'status',
            'expected_amount_lbc',
            'actual_amount_lbc',
            'pay_to_address',
            'txid',
            'confirmations',
            'expires_at',
            'client_request_id',
            'external_reference',
            'paid_at',
            'paid_by_id',
            'paid_note',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_currency_display(self, obj):
        if obj.currency == LEGACY_CHAIN_CURRENCY_CODE:
            return TOKEN_SYMBOL
        return obj.currency


class UserShippingAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserShippingAddress
        fields = (
            'id',
            'receiver_name',
            'phone',
            'country',
            'province',
            'city',
            'district',
            'street_address',
            'postal_code',
            'is_default',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def create(self, validated_data):
        user = self.context['request'].user
        is_default = bool(validated_data.get('is_default'))
        if is_default:
            UserShippingAddress.objects.filter(user=user, is_default=True).update(is_default=False)
        elif not UserShippingAddress.objects.filter(user=user).exists():
            validated_data['is_default'] = True
        return UserShippingAddress.objects.create(user=user, **validated_data)

    def update(self, instance, validated_data):
        is_default = validated_data.get('is_default')
        if is_default:
            UserShippingAddress.objects.filter(user=instance.user, is_default=True).exclude(id=instance.id).update(is_default=False)
        return super().update(instance, validated_data)


class MobileShippingAddressSerializer(serializers.ModelSerializer):
    state = serializers.CharField(source='province', required=False, allow_blank=True)
    address_line1 = serializers.CharField(source='street_address')
    address_line2 = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = UserShippingAddress
        fields = (
            'id',
            'receiver_name',
            'phone',
            'country',
            'state',
            'city',
            'district',
            'address_line1',
            'address_line2',
            'postal_code',
            'is_default',
        )
        read_only_fields = ('id',)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data['address_line2'] = ''
        return data

    def create(self, validated_data):
        validated_data.pop('address_line2', None)
        user = self.context['request'].user
        is_default = bool(validated_data.get('is_default'))
        if is_default:
            UserShippingAddress.objects.filter(user=user, is_default=True).update(is_default=False)
        elif not UserShippingAddress.objects.filter(user=user).exists():
            validated_data['is_default'] = True
        return UserShippingAddress.objects.create(user=user, **validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('address_line2', None)
        is_default = validated_data.get('is_default')
        if is_default:
            UserShippingAddress.objects.filter(user=instance.user, is_default=True).exclude(id=instance.id).update(is_default=False)
        return super().update(instance, validated_data)


class ProductShipmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductShipment
        fields = (
            'carrier',
            'tracking_number',
            'tracking_url',
            'shipped_note',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('created_at', 'updated_at')


class SellerPayoutSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = SellerPayout
        fields = (
            'amount',
            'currency',
            'status',
            'payout_address',
            'txid',
            'note',
            'failure_note',
            'paid_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class ProductOrderCreateSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    shipping_address_id = serializers.IntegerField(required=False, allow_null=True)
    payment_asset = serializers.ChoiceField(choices=ProductOrder.PAYMENT_ASSET_CHOICES)

    def validate(self, attrs):
        request = self.context['request']
        product = Product.objects.select_related('store').filter(pk=attrs['product_id']).first()
        if product is None:
            raise serializers.ValidationError({'product_id': ['Product not found.']})
        if product.status != Product.STATUS_ACTIVE:
            raise serializers.ValidationError({'product_id': ['Product is not active.']})
        if not product.store.is_active:
            raise serializers.ValidationError({'product_id': ['Seller store is inactive.']})
        if product.stock_quantity < attrs['quantity']:
            raise serializers.ValidationError({'quantity': ['Insufficient stock.']})
        shipping_address = None
        shipping_address_id = attrs.get('shipping_address_id')
        if shipping_address_id is not None:
            shipping_address = UserShippingAddress.objects.filter(id=shipping_address_id, user=request.user).first()
            if shipping_address is None:
                raise serializers.ValidationError({'shipping_address_id': ['Shipping address not found.']})
        attrs['product'] = product
        attrs['shipping_address'] = shipping_address
        return attrs


class ProductOrderDetailSerializer(serializers.ModelSerializer):
    expected_amount = serializers.DecimalField(source='total_amount', max_digits=12, decimal_places=2, read_only=True)
    pay_to_address = serializers.SerializerMethodField()
    expires_at = serializers.SerializerMethodField()
    qr_payload = serializers.SerializerMethodField()
    qr_text = serializers.SerializerMethodField()
    payment_uri = serializers.SerializerMethodField()
    shipment = ProductShipmentSerializer(read_only=True)
    payout = serializers.SerializerMethodField()
    payment_state = serializers.SerializerMethodField()
    payment_summary = serializers.SerializerMethodField()
    refund_summary = serializers.SerializerMethodField()
    product_name_snapshot = serializers.SerializerMethodField()
    product_thumbnail_snapshot = serializers.SerializerMethodField()
    product_snapshot = serializers.SerializerMethodField()

    class Meta:
        model = ProductOrder
        fields = (
            'order_no',
            'status',
            'payment_method',
            'payment_asset',
            'expected_amount',
            'unit_price_snapshot',
            'total_amount_snapshot',
            'platform_fee_rate',
            'platform_fee_amount',
            'seller_receivable_amount',
            'currency',
            'pay_to_address',
            'expires_at',
            'qr_payload',
            'qr_text',
            'payment_uri',
            'product_title_snapshot',
            'product_name_snapshot',
            'product_thumbnail_snapshot',
            'product_snapshot',
            'product_price_snapshot',
            'quantity',
            'total_amount',
            'shipping_address_snapshot',
            'paid_at',
            'stock_locked_at',
            'stock_released_at',
            'cancelled_at',
            'cancel_reason',
            'shipped_at',
            'completed_at',
            'settled_at',
            'payment_state',
            'payment_summary',
            'shipment',
            'payout',
            'refund_summary',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_product_name_snapshot(self, obj):
        return obj.product_title_snapshot or (obj.product.title if obj.product_id else '')

    def get_product_thumbnail_snapshot(self, obj):
        product = getattr(obj, 'product', None)
        if product is None or not product.cover_image:
            return None
        request = self.context.get('request')
        if request is None:
            return product.cover_image.url
        return request.build_absolute_uri(product.cover_image.url)

    def get_product_snapshot(self, obj):
        return {
            'name': self.get_product_name_snapshot(obj),
            'thumbnail_url': self.get_product_thumbnail_snapshot(obj),
        }

    def get_pay_to_address(self, obj):
        if obj.payment_method == ProductOrder.PAYMENT_METHOD_PLATFORM_ASSET:
            return None
        return obj.payment_order.pay_to_address if obj.payment_order else ''

    def get_expires_at(self, obj):
        return obj.payment_order.expires_at if obj.payment_order else None

    def get_qr_payload(self, obj):
        if obj.payment_method == ProductOrder.PAYMENT_METHOD_PLATFORM_ASSET:
            return None
        if obj.status != ProductOrder.STATUS_PENDING_PAYMENT or not obj.payment_order:
            return None
        return ProductOrderService().build_qr_payload(obj)

    def get_qr_text(self, obj):
        payload = self.get_qr_payload(obj)
        if payload is None:
            return ''
        return json.dumps(payload, separators=(',', ':'), sort_keys=True)

    def get_payment_uri(self, obj):
        if obj.payment_method == ProductOrder.PAYMENT_METHOD_PLATFORM_ASSET:
            return None
        if obj.status != ProductOrder.STATUS_PENDING_PAYMENT or not obj.payment_order:
            return ''
        return f'ltt:{obj.payment_order.pay_to_address}?amount={obj.total_amount}&token={obj.currency}&order_no={obj.order_no}'

    def get_payout(self, obj):
        if not hasattr(obj, 'seller_payout'):
            return None
        return SellerPayoutSummarySerializer(obj.seller_payout).data

    def get_payment_state(self, obj):
        payment = obj.payment_order
        if payment is None:
            return 'pending'
        if payment.status == PaymentOrder.STATUS_PENDING:
            return 'submitted' if (payment.txid or '').strip() else 'pending'
        if payment.status in {
            PaymentOrder.STATUS_PAID,
            PaymentOrder.STATUS_UNDERPAID,
            PaymentOrder.STATUS_OVERPAID,
            PaymentOrder.STATUS_FAILED,
            PaymentOrder.STATUS_EXPIRED,
            PaymentOrder.STATUS_CANCELLED,
        }:
            return payment.status
        return payment.status

    def get_payment_summary(self, obj):
        payment = obj.payment_order
        if payment is None and obj.payment_method == ProductOrder.PAYMENT_METHOD_PLATFORM_ASSET:
            return {
                'payment_method': ProductOrder.PAYMENT_METHOD_PLATFORM_ASSET,
                'payment_status': ProductOrder.STATUS_PAID if obj.status == ProductOrder.STATUS_PAID else obj.status,
                'txid': '',
                'confirmations': 0,
                'actual_amount': obj.total_amount_snapshot,
                'expected_amount': obj.total_amount_snapshot,
                'pay_to_address': None,
                'paid_at': obj.paid_at,
                'expires_at': None,
            }
        if payment is None:
            return None
        return {
            'payment_method': obj.payment_method,
            'payment_status': payment.status,
            'txid': payment.txid,
            'confirmations': payment.confirmations,
            'actual_amount': payment.actual_amount_lbc,
            'expected_amount': obj.total_amount,
            'pay_to_address': payment.pay_to_address,
            'paid_at': payment.paid_at,
            'expires_at': payment.expires_at,
        }

    def get_refund_summary(self, obj):
        latest = obj.refund_requests.order_by('-created_at', '-id').first()
        active_exists = obj.refund_requests.filter(
            status__in=[ProductRefundRequest.STATUS_REQUESTED, ProductRefundRequest.STATUS_APPROVED]
        ).exists()
        if latest is None:
            return {
                'latest_refund_request': None,
                'active_refund_request_exists': active_exists,
            }
        return {
            'latest_refund_request': {
                'id': latest.id,
                'status': latest.status,
                'requested_amount': latest.requested_amount,
                'currency': latest.currency,
                'updated_at': latest.updated_at,
            },
            'active_refund_request_exists': active_exists,
        }


class ProductOrderShipSerializer(serializers.Serializer):
    carrier = serializers.CharField(max_length=255)
    tracking_number = serializers.CharField(max_length=255)
    tracking_url = serializers.URLField(required=False, allow_blank=True)
    shipped_note = serializers.CharField(required=False, allow_blank=True)


class ProductOrderMarkSettledSerializer(serializers.Serializer):
    txid = serializers.CharField(required=False, allow_blank=True, max_length=255)
    payout_address = serializers.CharField(required=False, allow_blank=True, max_length=255)
    note = serializers.CharField(required=False, allow_blank=True)


class ProductOrderTxHintSerializer(serializers.Serializer):
    txid = serializers.CharField(max_length=128)


class PaymentQRResolveSerializer(serializers.Serializer):
    payload = serializers.CharField()


class SellerProductOrderListSerializer(serializers.ModelSerializer):
    buyer = serializers.SerializerMethodField()
    payment_summary = serializers.SerializerMethodField()
    shipment = ProductShipmentSerializer(read_only=True)
    payout = serializers.SerializerMethodField()

    class Meta:
        model = ProductOrder
        fields = (
            'order_no',
            'buyer',
            'product_title_snapshot',
            'product_price_snapshot',
            'quantity',
            'total_amount',
            'currency',
            'status',
            'payment_summary',
            'shipping_address_snapshot',
            'shipment',
            'payout',
            'created_at',
            'updated_at',
            'paid_at',
            'shipped_at',
            'completed_at',
            'settled_at',
        )
        read_only_fields = fields

    def get_buyer(self, obj):
        buyer = obj.buyer
        return {'id': buyer.id, 'email': buyer.email, 'display_name': buyer.display_name}

    def get_payment_summary(self, obj):
        payment = obj.payment_order
        if not payment:
            return None
        return {
            'status': payment.status,
            'amount': payment.amount,
            'currency': payment.currency,
            'txid': payment.txid,
            'confirmations': payment.confirmations,
        }

    def get_payout(self, obj):
        if not hasattr(obj, 'seller_payout'):
            return None
        return SellerPayoutSummarySerializer(obj.seller_payout).data


class SellerPayoutAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = SellerPayoutAddress
        fields = (
            'id',
            'blockchain',
            'token_symbol',
            'address',
            'label',
            'is_default',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'blockchain', 'token_symbol', 'created_at', 'updated_at')


class ProductRefundRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductRefundRequest
        fields = (
            'id',
            'product_order',
            'requester',
            'reason',
            'status',
            'requested_amount',
            'currency',
            'admin_note',
            'seller_note',
            'refund_txid',
            'created_at',
            'updated_at',
            'resolved_at',
        )
        read_only_fields = (
            'id',
            'product_order',
            'requester',
            'status',
            'currency',
            'admin_note',
            'seller_note',
            'refund_txid',
            'created_at',
            'updated_at',
            'resolved_at',
        )


class ProductRefundRequestCreateSerializer(serializers.Serializer):
    reason = serializers.CharField()
    requested_amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class ProductRefundAdminActionSerializer(serializers.Serializer):
    admin_note = serializers.CharField(required=False, allow_blank=True)
    refund_txid = serializers.CharField(required=False, allow_blank=True, max_length=255)


class BillingPlanSerializer(serializers.ModelSerializer):
    amount = serializers.DecimalField(source='price_amount', max_digits=12, decimal_places=2, read_only=True)
    currency = serializers.CharField(source='price_currency', read_only=True)
    interval = serializers.CharField(source='billing_interval', read_only=True)

    class Meta:
        model = BillingPlan
        fields = (
            'id',
            'code',
            'name',
            'description',
            'wallet_address',
            'amount',
            'currency',
            'interval',
            'billing_interval',
            'price_amount',
            'price_currency',
            'is_active',
        )
        read_only_fields = fields


class BillingSubscriptionCreateSerializer(serializers.Serializer):
    plan_id = serializers.IntegerField()

    def validate(self, attrs):
        plan_id = attrs['plan_id']
        plan = BillingPlan.objects.filter(pk=plan_id, is_active=True).first()
        if plan is None:
            raise serializers.ValidationError({'plan_id': ['Active billing plan not found.']})
        attrs['plan'] = plan
        return attrs


class BillingSubscriptionSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    current_period_start = serializers.DateTimeField(source='started_at', read_only=True)
    cancel_at = serializers.DateTimeField(source='cancelled_at', read_only=True)
    raw_status = serializers.CharField(source='status', read_only=True)
    plan = BillingPlanSerializer(read_only=True)

    class Meta:
        model = BillingSubscription
        fields = (
            'id',
            'status',
            'raw_status',
            'auto_renew',
            'current_period_start',
            'cancel_at',
            'started_at',
            'current_period_end',
            'cancelled_at',
            'created_at',
            'updated_at',
            'plan',
        )
        read_only_fields = fields

    def get_status(self, obj):
        # Frontend-compatible status mapping.
        if obj.status in {BillingSubscription.STATUS_CANCELLED, BillingSubscription.STATUS_EXPIRED}:
            return 'cancel_at_period_end'
        if obj.status == BillingSubscription.STATUS_ACTIVE and not obj.auto_renew:
            return 'cancel_at_period_end'
        return 'active'


class MembershipPlanSerializer(serializers.ModelSerializer):
    settlement = serializers.SerializerMethodField()
    supported_payment_assets = serializers.SerializerMethodField()
    base_price_amount = serializers.SerializerMethodField()
    payment_asset_options = serializers.SerializerMethodField()

    class Meta:
        model = MembershipPlan
        fields = (
            'id',
            'code',
            'name',
            'description',
            'price_lbc',
            'base_price_amount',
            'base_price_asset',
            'supported_payment_assets',
            'payment_asset_options',
            'settlement',
            'duration_days',
            'is_active',
            'sort_order',
        )
        read_only_fields = fields

    def get_settlement(self, obj):
        return {
            'blockchain': BLOCKCHAIN_NAME,
            'token_name': TOKEN_NAME,
            'token_symbol': TOKEN_SYMBOL,
            'token_peg': TOKEN_PEG,
        }

    def get_supported_payment_assets(self, obj):
        assets = []
        if obj.allow_blockchain_payment:
            assets.append(PaymentOrder.PAYMENT_ASSET_THB_LTT)
        if obj.allow_meow_points_payment:
            assets.append(PaymentOrder.PAYMENT_ASSET_MEOW_POINTS)
        if obj.allow_meow_credit_payment:
            assets.append(PaymentOrder.PAYMENT_ASSET_MEOW_CREDIT)
        return assets

    def get_base_price_amount(self, obj):
        return obj.base_price_amount if obj.base_price_amount is not None else obj.price_lbc

    def get_payment_asset_options(self, obj):
        base_amount = self.get_base_price_amount(obj)
        options = []
        for asset_code in self.get_supported_payment_assets(obj):
            rate = get_membership_payment_asset_rate(asset_code)
            display_name = dict(PaymentAssetRate.ASSET_CHOICES).get(asset_code, asset_code)
            configured = PaymentAssetRate.objects.filter(asset_code=asset_code, is_active=True).order_by('sort_order', 'asset_code').first()
            if configured and configured.display_name:
                display_name = configured.display_name
            options.append(
                {
                    'asset_code': asset_code,
                    'display_name': display_name,
                    'exchange_rate': f'{rate:.8f}',
                    'estimated_payment_amount': f'{(base_amount * rate):.8f}',
                }
            )
        return options


class ManualMembershipTxHintSubmitSerializer(serializers.Serializer):
    plan_code = serializers.CharField(max_length=32)
    txid = serializers.CharField(max_length=128)

    def validate_plan_code(self, value):
        plan_code = value.strip()
        if not plan_code:
            raise serializers.ValidationError('plan_code is required.')
        return plan_code

    def validate_txid(self, value):
        txid = value.strip()
        if not txid:
            raise serializers.ValidationError('txid is required.')
        return txid


class ManualMembershipPaymentHintSerializer(serializers.ModelSerializer):
    plan_code = serializers.CharField(source='plan.code', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)

    class Meta:
        model = ManualMembershipPayment
        fields = (
            'id',
            'txid',
            'plan_code',
            'plan_name',
            'expected_amount_lbc',
            'actual_amount_lbc',
            'pay_to_address',
            'confirmations',
            'status',
            'reject_reason',
            'created_at',
            'updated_at',
            'verified_at',
        )
        read_only_fields = fields


class MembershipOrderCreateSerializer(serializers.Serializer):
    # Phase 2A/2B contract intentionally uses plan_code (stable business key),
    # not plan_id, to reduce client coupling to internal DB identifiers.
    plan_code = serializers.ChoiceField(choices=MembershipPlan.CODE_CHOICES)
    payment_asset = serializers.ChoiceField(
        choices=PaymentOrder.PAYMENT_ASSET_CHOICES,
        required=False,
        default=PaymentOrder.PAYMENT_ASSET_THB_LTT,
    )

    def validate(self, attrs):
        plan = MembershipPlan.objects.filter(code=attrs['plan_code'], is_active=True).first()
        if plan is None:
            raise serializers.ValidationError({'plan_code': ['Active membership plan not found.']})
        attrs['plan'] = plan
        return attrs


class MembershipOrderSerializer(serializers.ModelSerializer):
    plan = serializers.SerializerMethodField()
    pay_to_address = serializers.SerializerMethodField()
    qr_text = serializers.SerializerMethodField()
    settlement = serializers.SerializerMethodField()
    plan_code = serializers.CharField(source='plan_code_snapshot', read_only=True)
    plan_name = serializers.CharField(source='plan_name_snapshot', read_only=True)
    payment_method = serializers.CharField(source='payment_method_code', read_only=True)
    qr_payload = serializers.SerializerMethodField()
    payment_uri = serializers.SerializerMethodField()
    display_payment_amount = serializers.SerializerMethodField()
    display_payment_asset = serializers.SerializerMethodField()

    class Meta:
        model = PaymentOrder
        fields = (
            'order_no',
            'plan_code',
            'plan_name',
            'plan',
            'payment_method',
            'payment_asset',
            'amount_snapshot',
            'exchange_rate_snapshot',
            'paid_amount',
            'display_payment_amount',
            'display_payment_asset',
            'expected_amount_lbc',
            'settlement',
            'pay_to_address',
            'qr_payload',
            'payment_uri',
            'qr_text',
            'status',
            'expires_at',
            'paid_at',
            'confirmations',
            'txid',
        )
        read_only_fields = fields

    def get_plan(self, obj):
        return {
            'id': obj.target_id,
            'code': obj.plan_code_snapshot,
            'name': obj.plan_name_snapshot,
        }

    def get_settlement(self, obj):
        return {
            'blockchain': BLOCKCHAIN_NAME,
            'token_name': TOKEN_NAME,
            'token_symbol': TOKEN_SYMBOL,
            'token_peg': TOKEN_PEG,
        }

    def get_pay_to_address(self, obj):
        if obj.payment_method_code == PaymentOrder.PAYMENT_METHOD_PLATFORM_ASSET:
            return None
        return obj.pay_to_address or None

    def get_qr_text(self, obj):
        return self.get_pay_to_address(obj)

    def get_qr_payload(self, obj):
        if obj.payment_method_code == PaymentOrder.PAYMENT_METHOD_PLATFORM_ASSET:
            return None
        return obj.pay_to_address or None

    def get_payment_uri(self, obj):
        if obj.payment_method_code == PaymentOrder.PAYMENT_METHOD_PLATFORM_ASSET:
            return None
        if not obj.pay_to_address or not obj.expected_amount_lbc:
            return None
        return f"{TOKEN_SYMBOL.lower()}:{obj.pay_to_address}?amount={obj.expected_amount_lbc}"

    def get_display_payment_amount(self, obj):
        if obj.payment_method_code == PaymentOrder.PAYMENT_METHOD_PLATFORM_ASSET and obj.paid_amount is not None:
            return obj.paid_amount
        if obj.expected_amount_lbc is not None:
            return obj.expected_amount_lbc
        return obj.amount_snapshot

    def get_display_payment_asset(self, obj):
        if obj.payment_method_code == PaymentOrder.PAYMENT_METHOD_PLATFORM_ASSET:
            return obj.payment_asset
        return PaymentOrder.PAYMENT_ASSET_THB_LTT


class MembershipOrderTxHintSerializer(serializers.Serializer):
    txid = serializers.CharField(max_length=128)

    def validate_txid(self, value):
        txid = value.strip()
        if not txid:
            raise serializers.ValidationError('txid is required.')
        return txid


class WalletPrototypePayOrderSerializer(serializers.Serializer):
    order_no = serializers.CharField(max_length=64)
    wallet_id = serializers.CharField(required=False, allow_blank=True, max_length=128)
    password = serializers.CharField(write_only=True, max_length=256)


class WalletPrototypePayProductOrderSerializer(serializers.Serializer):
    order_no = serializers.CharField(max_length=64)
    wallet_id = serializers.CharField(required=False, allow_blank=True, max_length=128)
    password = serializers.CharField(write_only=True, max_length=256)


class MyMembershipSerializer(serializers.Serializer):
    status = serializers.CharField()
    starts_at = serializers.DateTimeField(allow_null=True)
    ends_at = serializers.DateTimeField(allow_null=True)
    plan = serializers.DictField(allow_null=True)

    @classmethod
    def from_membership(cls, membership: UserMembership | None):
        if membership is None:
            return cls(
                {
                    'status': 'none',
                    'starts_at': None,
                    'ends_at': None,
                    'plan': None,
                }
            )
        return cls(
            {
                'status': membership.status,
                'starts_at': membership.starts_at,
                'ends_at': membership.ends_at,
                'plan': {
                    'id': membership.plan_id,
                    'code': membership.plan.code,
                    'name': membership.plan.name,
                },
            }
        )


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
            'access_type',
            'preview_seconds',
            'can_watch',
            'is_locked',
            'lock_reason',
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
            'can_watch',
            'is_locked',
            'lock_reason',
            'created_at',
            'updated_at',
        )

class VideoInteractionSummarySerializer(serializers.Serializer):
    video_id = serializers.IntegerField(source='id', read_only=True)
    like_count = serializers.IntegerField(read_only=True)
    comment_count = serializers.IntegerField(read_only=True)
    view_count = serializers.SerializerMethodField()
    share_count = serializers.IntegerField(read_only=True)
    gift_count = serializers.SerializerMethodField()
    gift_points_total = serializers.SerializerMethodField()
    gift_amount_total = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    viewer_has_liked = serializers.SerializerMethodField()
    viewer_is_following = serializers.SerializerMethodField()
    follower_count = serializers.IntegerField(source='owner.subscriber_count', read_only=True)
    # Backward-compatible aliases; keep for existing frontend payload consumers.
    viewer_is_subscribed = serializers.SerializerMethodField()
    channel_id = serializers.IntegerField(source='owner.id', read_only=True)
    subscriber_count = serializers.IntegerField(source='owner.subscriber_count', read_only=True)

    def get_view_count(self, obj):
        prefetched = getattr(obj, 'view_count', None)
        if prefetched is not None:
            return prefetched
        return obj.views.count()

    def get_gift_count(self, obj):
        value = GiftTransaction.objects.filter(video=obj).aggregate(total=Sum('quantity')).get('total')
        return value or 0

    def get_gift_points_total(self, obj):
        value = GiftTransaction.objects.filter(video=obj).aggregate(total=Sum('total_points')).get('total')
        return value or 0

    def get_gift_amount_total(self, obj):
        return sum(
            (tx.amount or tx.total_points or 0)
            for tx in GiftTransaction.objects.filter(video=obj).only('amount', 'total_points')
        )

    def get_is_liked(self, obj):
        return self.get_viewer_has_liked(obj)

    def get_viewer_has_liked(self, obj):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        prefetched = getattr(obj, 'is_liked_value', None)
        if prefetched is not None:
            return bool(prefetched)
        return VideoLike.objects.filter(video=obj, user=request.user).exists()

    def get_viewer_is_following(self, obj):
        request = self.context.get('request')
        if request is None or not request.user.is_authenticated:
            return False
        prefetched = getattr(obj, 'is_subscribed_value', None)
        if prefetched is not None:
            return bool(prefetched)
        return ChannelSubscription.objects.filter(channel=obj.owner, subscriber=request.user).exists()

    def get_viewer_is_subscribed(self, obj):
        return self.get_viewer_is_following(obj)


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
            'share_count',
            'is_liked',
            'thumbnail_url',
            'created_at',
        )
