from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import (
    BillingPlan,
    BillingSubscription,
    Category,
    ChainReceipt,
    ChannelSubscription,
    CommentLike,
    DramaEpisode,
    DramaFavorite,
    DramaSeries,
    DramaWatchProgress,
    LiveStream,
    LiveChatMessage,
    LiveChatRoom,
    LiveStreamProduct,
    MembershipPlan,
    MeowPointLedger,
    MeowPointPackage,
    MeowPointPurchase,
    MeowPointWallet,
    OrderPayment,
    PaymentOrder,
    StreamPaymentMethod,
    Product,
    SellerStore,
    User,
    UserMembership,
    Video,
    VideoComment,
    VideoLike,
    VideoView,
    WalletAddress,
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


@admin.register(DramaSeries)
class DramaSeriesAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'category',
        'status',
        'is_active',
        'total_episodes',
        'view_count',
        'favorite_count',
        'created_at',
        'updated_at',
    )
    list_filter = ('status', 'is_active', 'category', 'created_at')
    search_fields = ('title', 'description', 'category__name', 'category__slug')
    ordering = ('-created_at', '-id')
    readonly_fields = ('view_count', 'favorite_count', 'created_at', 'updated_at')
    autocomplete_fields = ('category',)


@admin.register(DramaEpisode)
class DramaEpisodeAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'series',
        'episode_no',
        'title',
        'is_free',
        'unlock_type',
        'meow_points_price',
        'sort_order',
        'is_active',
        'created_at',
        'updated_at',
    )
    list_filter = ('is_active', 'is_free', 'unlock_type', 'created_at')
    search_fields = ('title', 'series__title')
    ordering = ('series', 'sort_order', 'episode_no', 'id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('series',)


@admin.register(DramaWatchProgress)
class DramaWatchProgressAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'series', 'episode', 'progress_seconds', 'completed', 'updated_at')
    list_filter = ('completed', 'updated_at')
    search_fields = ('user__email', 'series__title', 'episode__title')
    ordering = ('-updated_at', '-id')
    readonly_fields = ('updated_at',)
    autocomplete_fields = ('user', 'series', 'episode')


@admin.register(DramaFavorite)
class DramaFavoriteAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'series', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__email', 'series__title')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('user', 'series')


@admin.register(MeowPointWallet)
class MeowPointWalletAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'balance', 'total_earned', 'total_spent', 'updated_at')
    search_fields = ('user__email',)
    ordering = ('-updated_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('user',)


@admin.register(MeowPointPackage)
class MeowPointPackageAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'points_amount', 'bonus_points', 'price_amount', 'price_currency', 'status')
    list_filter = ('status', 'price_currency')
    search_fields = ('code', 'name', 'description')
    ordering = ('sort_order', 'id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(MeowPointLedger)
class MeowPointLedgerAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'entry_type', 'amount', 'balance_before', 'balance_after', 'created_at')
    list_filter = ('entry_type', 'created_at')
    search_fields = ('user__email', 'target_type', 'note')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('user', 'payment_order')


@admin.register(MeowPointPurchase)
class MeowPointPurchaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'order_no', 'user', 'package_code_snapshot', 'total_points', 'price_amount', 'status', 'created_at')
    list_filter = ('status', 'price_currency', 'created_at')
    search_fields = ('order_no', 'user__email', 'package_code_snapshot', 'package_name_snapshot')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at', 'paid_at', 'credited_at')
    autocomplete_fields = ('user', 'package', 'payment_order')


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
        'order_no',
        'order_type',
        'status',
        'amount',
        'currency',
        'expected_amount_lbc',
        'actual_amount_lbc',
        'pay_to_address',
        'stream',
        'product',
        'user',
        'created_at',
    )
    list_filter = ('order_type', 'status', 'currency', 'target_type', 'created_at')
    search_fields = (
        'order_no',
        'external_reference',
        'pay_to_address',
        'txid',
        'user__email',
        'stream__title',
        'product__title',
        'plan_code_snapshot',
        'plan_name_snapshot',
    )
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('user', 'stream', 'product', 'payment_method', 'wallet_address')


@admin.register(MembershipPlan)
class MembershipPlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'price_lbc', 'duration_days', 'is_active', 'sort_order')
    list_filter = ('is_active', 'code')
    search_fields = ('code', 'name', 'description')
    ordering = ('sort_order', 'id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WalletAddress)
class WalletAddressAdmin(admin.ModelAdmin):
    list_display = ('id', 'address', 'wallet_id', 'account_id', 'label', 'usage_type', 'status', 'assigned_order', 'assigned_at')
    list_filter = ('usage_type', 'status', 'created_at')
    search_fields = ('address', 'wallet_id', 'account_id', 'label', 'assigned_order__order_no', 'assigned_order__external_reference')
    ordering = ('-id',)
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('assigned_order',)


@admin.register(ChainReceipt)
class ChainReceiptAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'currency',
        'wallet_id',
        'txid',
        'vout',
        'address',
        'amount_lbc',
        'confirmations',
        'match_status',
        'matched_order',
        'seen_at',
    )
    list_filter = ('currency', 'match_status', 'confirmations', 'created_at')
    search_fields = ('txid', 'wallet_id', 'address', 'matched_order__order_no', 'matched_order__pay_to_address')
    ordering = ('-seen_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('matched_order',)


@admin.register(OrderPayment)
class OrderPaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'order', 'receipt', 'txid', 'amount_lbc', 'confirmations', 'payment_status', 'matched_at')
    list_filter = ('payment_status', 'created_at')
    search_fields = ('txid', 'order__order_no', 'receipt__txid', 'order__external_reference')
    ordering = ('-matched_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('order', 'receipt')


@admin.register(UserMembership)
class UserMembershipAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'plan', 'status', 'starts_at', 'ends_at', 'source_order')
    list_filter = ('status', 'plan__code', 'created_at')
    search_fields = ('user__email', 'plan__code', 'plan__name', 'source_order__order_no')
    ordering = ('-ends_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('user', 'plan', 'source_order')


@admin.register(BillingPlan)
class BillingPlanAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'billing_interval', 'price_amount', 'price_currency', 'wallet_address', 'is_active')
    list_filter = ('billing_interval', 'price_currency', 'is_active')
    search_fields = ('code', 'name', 'description', 'wallet_address')
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
