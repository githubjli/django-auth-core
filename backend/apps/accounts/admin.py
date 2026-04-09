from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import (
    BillingPlan,
    BillingSubscription,
    Category,
    ChannelSubscription,
    CommentLike,
    LiveStream,
    LiveChatMessage,
    LiveChatRoom,
    LiveStreamProduct,
    PaymentOrder,
    StreamPaymentMethod,
    Product,
    SellerStore,
    User,
    Video,
    VideoComment,
    VideoLike,
    VideoView,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'sort_order', 'show_on_homepage', 'is_active', 'created_at')
    list_filter = ('is_active', 'show_on_homepage')
    search_fields = ('name', 'slug', 'description')
    ordering = ('sort_order', 'name')
    readonly_fields = ('created_at',)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    ordering = ('email',)
    list_display = (
        'email',
        'display_name',
        'first_name',
        'last_name',
        'language',
        'theme',
        'is_creator',
        'subscriber_count',
        'is_staff',
        'is_active',
        'date_joined',
    )
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'is_creator')
    search_fields = ('email', 'first_name', 'last_name', 'bio')
    readonly_fields = ('date_joined', 'last_login', 'subscriber_count')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        (
            'Personal info',
            {'fields': ('first_name', 'last_name', 'avatar', 'bio', 'subscriber_count')},
        ),
        ('Preferences', {'fields': ('language', 'theme', 'timezone')}),
        (
            'Permissions',
            {
                'fields': (
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'is_creator',
                    'groups',
                    'user_permissions',
                ),
            },
        ),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('email', 'password1', 'password2', 'is_staff', 'is_active', 'is_creator'),
            },
        ),
    )


@admin.register(LiveStream)
class LiveStreamAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'owner',
        'visibility',
        'status',
        'payment_address',
        'viewer_count',
        'created_at',
    )
    list_filter = ('visibility', 'status', 'created_at')
    search_fields = ('title', 'description', 'payment_address', 'owner__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('stream_key', 'viewer_count', 'started_at', 'ended_at', 'created_at')
    autocomplete_fields = ('owner', 'category')


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'owner',
        'category',
        'status',
        'visibility',
        'like_count',
        'comment_count',
        'created_at',
        'updated_at',
    )
    list_filter = ('status', 'visibility', 'category', 'created_at')
    search_fields = ('title', 'description', 'owner__email', 'owner__first_name', 'owner__last_name')
    ordering = ('-created_at', '-id')
    readonly_fields = ('like_count', 'comment_count', 'created_at', 'updated_at')
    autocomplete_fields = ('owner', 'category')


@admin.register(VideoLike)
class VideoLikeAdmin(admin.ModelAdmin):
    list_display = ('id', 'video', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('video__title', 'user__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('video', 'user')


@admin.register(VideoView)
class VideoViewAdmin(admin.ModelAdmin):
    list_display = ('id', 'video', 'viewer', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('video__title', 'viewer__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('video', 'viewer')


@admin.register(ChannelSubscription)
class ChannelSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'channel', 'subscriber', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('channel__email', 'subscriber__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('channel', 'subscriber')


@admin.register(VideoComment)
class VideoCommentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'video',
        'user',
        'parent',
        'is_deleted',
        'like_count',
        'reply_count',
        'created_at',
        'updated_at',
    )
    list_filter = ('is_deleted', 'created_at', 'video__category')
    search_fields = ('content', 'video__title', 'user__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('like_count', 'reply_count', 'created_at', 'updated_at')
    autocomplete_fields = ('video', 'user', 'parent')


@admin.register(CommentLike)
class CommentLikeAdmin(admin.ModelAdmin):
    list_display = ('id', 'comment', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('comment__content', 'comment__video__title', 'user__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('comment', 'user')


@admin.register(SellerStore)
class SellerStoreAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'slug', 'owner', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'slug', 'owner__email', 'owner__first_name', 'owner__last_name')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('owner',)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'slug',
        'store',
        'price_amount',
        'price_currency',
        'stock_quantity',
        'status',
        'created_at',
        'updated_at',
    )
    list_filter = ('status', 'price_currency', 'created_at')
    search_fields = ('title', 'slug', 'store__name', 'store__slug', 'store__owner__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('store',)


@admin.register(LiveStreamProduct)
class LiveStreamProductAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'stream',
        'product',
        'sort_order',
        'is_pinned',
        'is_active',
        'start_at',
        'end_at',
        'created_at',
    )
    list_filter = ('is_active', 'is_pinned', 'created_at')
    search_fields = ('stream__title', 'product__title', 'stream__owner__email', 'product__store__owner__email')
    ordering = ('sort_order', '-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('stream', 'product')


@admin.register(LiveChatRoom)
class LiveChatRoomAdmin(admin.ModelAdmin):
    list_display = ('id', 'stream', 'is_enabled', 'slow_mode_seconds', 'created_at')
    list_filter = ('is_enabled', 'created_at')
    search_fields = ('stream__title', 'stream__owner__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('stream',)


@admin.register(LiveChatMessage)
class LiveChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'room', 'user', 'message_type', 'is_pinned', 'is_deleted', 'created_at')
    list_filter = ('message_type', 'is_pinned', 'is_deleted', 'created_at')
    search_fields = ('content', 'room__stream__title', 'user__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('room', 'user', 'reply_to', 'product')


@admin.register(StreamPaymentMethod)
class StreamPaymentMethodAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'stream',
        'method_type',
        'title',
        'is_active',
        'sort_order',
        'created_at',
        'updated_at',
    )
    list_filter = ('method_type', 'is_active', 'created_at')
    search_fields = ('title', 'stream__title', 'stream__owner__email', 'wallet_address', 'qr_text')
    ordering = ('sort_order', '-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('stream',)


@admin.register(PaymentOrder)
class PaymentOrderAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'order_type',
        'status',
        'amount',
        'currency',
        'stream',
        'product',
        'user',
        'created_at',
    )
    list_filter = ('order_type', 'status', 'currency', 'created_at')
    search_fields = ('external_reference', 'user__email', 'stream__title', 'product__title')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('user', 'stream', 'product', 'payment_method')


@admin.register(BillingPlan)
class BillingPlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'billing_interval', 'price_amount', 'price_currency', 'is_active')
    list_filter = ('billing_interval', 'price_currency', 'is_active')
    search_fields = ('code', 'name', 'description')
    ordering = ('price_amount', 'id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(BillingSubscription)
class BillingSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'plan', 'status', 'auto_renew', 'started_at', 'cancelled_at')
    list_filter = ('status', 'auto_renew', 'created_at')
    search_fields = ('user__email', 'plan__code', 'plan__name')
    ordering = ('-created_at', '-id')
    readonly_fields = ('started_at', 'created_at', 'updated_at')
    autocomplete_fields = ('user', 'plan')
