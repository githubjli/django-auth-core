import json

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.accounts.constants import BLOCKCHAIN_NAME, LEGACY_CHAIN_CURRENCY_CODE, TOKEN_NAME, TOKEN_PEG, TOKEN_SYMBOL
from apps.accounts.models import (
    BillingPlan,
    BillingSubscription,
    MembershipPlan,
    Category,
    ChannelSubscription,
    LiveChatMessage,
    LiveChatRoom,
    LiveStream,
    LiveStreamProduct,
    PaymentOrder,
    Product,
    ProductOrder,
    ProductRefundRequest,
    ProductShipment,
    SellerPayoutAddress,
    SellerStore,
    SellerPayout,
    StreamPaymentMethod,
    UserShippingAddress,
    Video,
    VideoComment,
    VideoLike,
    UserMembership,
)
from apps.accounts.services import AntMediaLiveAdapter, ProductOrderService

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
    display_name = serializers.CharField(read_only=True)
    avatar_url = serializers.SerializerMethodField()
    is_admin = serializers.SerializerMethodField()

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

    def _summary(self, obj):
        summary = getattr(obj, '_account_profile_summary_cache', None)
        if summary is not None:
            return summary

        seller_store = SellerStore.objects.filter(owner=obj).only('id', 'name', 'slug', 'is_active').first()
        product_count = Product.objects.filter(store__owner=obj).count()
        payment_method_count = StreamPaymentMethod.objects.filter(stream__owner=obj).count()
        summary = {
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
                'videos': Video.objects.filter(owner=obj).count(),
                'live_streams': LiveStream.objects.filter(owner=obj).count(),
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
            'title',
            'description',
            'description_preview',
            'visibility',
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
        request = self.context.get('request')
        if not obj.owner.avatar:
            return None
        if request is None:
            return obj.owner.avatar.url
        return request.build_absolute_uri(obj.owner.avatar.url)

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
            'rtmp_url',
            'playback_url',
            'watch_url',
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
            'owner_avatar_url',
            'creator',
            'category_name',
            'status',
            'django_status',
            'effective_status',
            'status_source',
            'raw_ant_media_status',
            'rtmp_url',
            'playback_url',
            'watch_url',
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
    cover_image_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            'id',
            'store_id',
            'title',
            'slug',
            'description',
            'cover_image',
            'cover_image_url',
            'price_amount',
            'price_currency',
            'stock_quantity',
            'status',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'store_id',
            'created_at',
            'updated_at',
        )

    def get_cover_image_url(self, obj):
        request = self.context.get('request')
        if not obj.cover_image:
            return None
        if request is None:
            return obj.cover_image.url
        return request.build_absolute_uri(obj.cover_image.url)


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

    class Meta:
        model = LiveChatMessage
        fields = (
            'id',
            'live_id',
            'message_type',
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
    shipping_address_id = serializers.IntegerField()

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
        shipping_address = UserShippingAddress.objects.filter(id=attrs['shipping_address_id'], user=request.user).first()
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
    payment_summary = serializers.SerializerMethodField()
    refund_summary = serializers.SerializerMethodField()

    class Meta:
        model = ProductOrder
        fields = (
            'order_no',
            'status',
            'expected_amount',
            'currency',
            'pay_to_address',
            'expires_at',
            'qr_payload',
            'qr_text',
            'payment_uri',
            'product_title_snapshot',
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
            'payment_summary',
            'shipment',
            'payout',
            'refund_summary',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_pay_to_address(self, obj):
        return obj.payment_order.pay_to_address if obj.payment_order else ''

    def get_expires_at(self, obj):
        return obj.payment_order.expires_at if obj.payment_order else None

    def get_qr_payload(self, obj):
        if obj.status != ProductOrder.STATUS_PENDING_PAYMENT or not obj.payment_order:
            return None
        return ProductOrderService().build_qr_payload(obj)

    def get_qr_text(self, obj):
        payload = self.get_qr_payload(obj)
        if payload is None:
            return ''
        return json.dumps(payload, separators=(',', ':'), sort_keys=True)

    def get_payment_uri(self, obj):
        if obj.status != ProductOrder.STATUS_PENDING_PAYMENT or not obj.payment_order:
            return ''
        return f'ltt:{obj.payment_order.pay_to_address}?amount={obj.total_amount}&token={obj.currency}&order_no={obj.order_no}'

    def get_payout(self, obj):
        if not hasattr(obj, 'seller_payout'):
            return None
        return SellerPayoutSummarySerializer(obj.seller_payout).data

    def get_payment_summary(self, obj):
        payment = obj.payment_order
        if payment is None:
            return None
        return {
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
    txid = serializers.CharField(max_length=255)
    payout_address = serializers.CharField(required=False, allow_blank=True, max_length=255)
    note = serializers.CharField(required=False, allow_blank=True)


class ProductOrderTxHintSerializer(serializers.Serializer):
    txid = serializers.CharField(max_length=128)


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

    class Meta:
        model = MembershipPlan
        fields = (
            'id',
            'code',
            'name',
            'description',
            'price_lbc',
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


class MembershipOrderCreateSerializer(serializers.Serializer):
    # Phase 2A/2B contract intentionally uses plan_code (stable business key),
    # not plan_id, to reduce client coupling to internal DB identifiers.
    plan_code = serializers.ChoiceField(choices=MembershipPlan.CODE_CHOICES)

    def validate(self, attrs):
        plan = MembershipPlan.objects.filter(code=attrs['plan_code'], is_active=True).first()
        if plan is None:
            raise serializers.ValidationError({'plan_code': ['Active membership plan not found.']})
        attrs['plan'] = plan
        return attrs


class MembershipOrderSerializer(serializers.ModelSerializer):
    plan = serializers.SerializerMethodField()
    qr_text = serializers.CharField(source='pay_to_address', read_only=True)
    settlement = serializers.SerializerMethodField()

    class Meta:
        model = PaymentOrder
        fields = (
            'order_no',
            'plan',
            'expected_amount_lbc',
            'settlement',
            'pay_to_address',
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
    viewer_is_following = serializers.SerializerMethodField()
    follower_count = serializers.IntegerField(source='owner.subscriber_count', read_only=True)
    # Backward-compatible aliases; keep for existing frontend payload consumers.
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
            'is_liked',
            'thumbnail_url',
            'created_at',
        )
