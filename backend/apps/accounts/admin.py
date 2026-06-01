from django.contrib import admin
from django.core.exceptions import ValidationError
from django.utils.html import format_html
from django.utils import timezone
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
    DramaUnlock,
    DramaSeries,
    DramaWatchProgress,
    DailyLoginReward,
    Gift,
    GiftTransaction,
    KycDocument,
    KycProfile,
    LiveStream,
    LiveChatMessage,
    LiveChatRoom,
    LiveStreamProduct,
    ManualMembershipPayment,
    MeowCreditLedger,
    MeowCreditPackage,
    MeowCreditRecharge,
    MeowCreditRedeemRequest,
    MeowCreditWallet,
    MembershipPlan,
    PaymentAssetRate,
    MeowPointLedger,
    MeowPointPackage,
    MeowPointPurchase,
    MeowPointWallet,
    OrderPayment,
    PaymentOrder,
    StreamPaymentMethod,
    Product,
    ProductCategory,
    ProductOrder,
    SavedProduct,
    SellerApplication,
    SellerPayout,
    PlatformAssetLedger,
    SellerStore,
    ShopBanner,
    UserAssetBalance,
    UserAssetTransaction,
    User,
    UserMembership,
    Video,
    VideoComment,
    VideoLike,
    VideoView,
    WalletAddress,
)
from apps.accounts.services import MeowCreditRechargeService, MeowCreditService, approve_seller_application


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
        'access_type',
        'preview_seconds',
        'like_count',
        'comment_count',
        'created_at',
        'updated_at',
    )
    list_filter = ('status', 'visibility', 'access_type', 'category', 'created_at')
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


@admin.register(DramaUnlock)
class DramaUnlockAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'series', 'episode', 'source', 'points_amount', 'unlocked_at')
    list_filter = ('source', 'unlocked_at')
    search_fields = ('user__email', 'series__title', 'episode__title')
    ordering = ('-unlocked_at', '-id')
    readonly_fields = ('unlocked_at',)
    autocomplete_fields = ('user', 'series', 'episode', 'ledger_entry')


@admin.register(KycProfile)
class KycProfileAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'status',
        'full_name',
        'nationality',
        'id_type',
        'id_number',
        'submitted_at',
        'reviewed_at',
        'reviewed_by',
    )
    list_filter = ('status', 'nationality', 'id_type')
    search_fields = ('user__email', 'full_name', 'id_number')
    readonly_fields = ('submitted_at', 'reviewed_at', 'reviewed_by', 'created_at', 'updated_at')
    autocomplete_fields = ('user',)
    actions = ('approve_selected_kyc', 'reject_selected_kyc')

    @admin.action(description='Approve selected KYC')
    def approve_selected_kyc(self, request, queryset):
        updated = queryset.update(
            status=KycProfile.STATUS_APPROVED,
            reviewed_at=timezone.now(),
            reviewed_by_id=request.user.pk,
            reject_reason='',
        )
        self.message_user(request, f'Approved {updated} KYC profile(s).')

    @admin.action(description='Reject selected KYC')
    def reject_selected_kyc(self, request, queryset):
        updated = queryset.update(
            status=KycProfile.STATUS_REJECTED,
            reviewed_at=timezone.now(),
            reviewed_by_id=request.user.pk,
            reject_reason='Rejected by admin',
        )
        self.message_user(request, f'Rejected {updated} KYC profile(s).')


@admin.register(KycDocument)
class KycDocumentAdmin(admin.ModelAdmin):
    list_display = ('user', 'kyc_profile', 'document_type', 'image_link', 'uploaded_at')
    list_filter = ('document_type', 'uploaded_at')
    search_fields = ('user__email', 'kyc_profile__full_name', 'kyc_profile__id_number')
    readonly_fields = ('uploaded_at', 'created_at', 'image_link')
    autocomplete_fields = ('user', 'kyc_profile')

    def image_link(self, obj):
        if not obj.image:
            return ''
        return format_html('<a href="{}" target="_blank">View image</a>', obj.image.url)

    image_link.short_description = 'Image'


@admin.register(MeowCreditWallet)
class MeowCreditWalletAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'balance', 'total_recharged', 'total_spent', 'total_redeemed', 'total_adjusted', 'created_at', 'updated_at')
    search_fields = ('user__email',)
    ordering = ('-updated_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('user',)


@admin.register(MeowCreditPackage)
class MeowCreditPackageAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'credit_amount', 'bonus_credit', 'price_amount', 'price_currency', 'status', 'created_at', 'updated_at')
    list_filter = ('status', 'price_currency')
    search_fields = ('code', 'name', 'description')
    ordering = ('sort_order', 'id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(MeowCreditLedger)
class MeowCreditLedgerAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'entry_type', 'status', 'amount', 'balance_before', 'balance_after', 'payment_order', 'created_at')
    list_filter = ('entry_type', 'status', 'created_at')
    search_fields = ('user__email', 'target_type', 'note', 'payment_order__order_no')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('user', 'payment_order')


@admin.register(MeowCreditRecharge)
class MeowCreditRechargeAdmin(admin.ModelAdmin):
    list_display = ('id', 'order_no', 'user', 'package_code_snapshot', 'total_credit', 'price_amount', 'price_currency', 'status', 'payment_order', 'created_at', 'updated_at')
    list_filter = ('status', 'price_currency', 'created_at')
    search_fields = ('order_no', 'user__email', 'package_code_snapshot', 'package_name_snapshot', 'payment_order__order_no')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at', 'paid_at', 'credited_at')
    autocomplete_fields = ('user', 'package', 'payment_order')
    actions = ('mark_payment_paid_and_credit',)

    @admin.action(description='Mark linked payment paid and credit wallet')
    def mark_payment_paid_and_credit(self, request, queryset):
        credited = 0
        skipped = 0
        service = MeowCreditRechargeService()
        for recharge in queryset.select_related('payment_order'):
            payment_order = recharge.payment_order
            if payment_order is None:
                skipped += 1
                continue
            if payment_order.status not in {PaymentOrder.STATUS_PAID, PaymentOrder.STATUS_OVERPAID}:
                payment_order.status = PaymentOrder.STATUS_PAID
                payment_order.paid_at = payment_order.paid_at or timezone.now()
                payment_order.save(update_fields=['status', 'paid_at', 'updated_at'])
            credited_recharge = service.credit_paid_recharge(recharge)
            if credited_recharge.credited_at is not None:
                credited += 1
            else:
                skipped += 1
        self.message_user(request, f'Meow Credit recharge action completed: credited={credited}, skipped={skipped}.')


@admin.register(MeowCreditRedeemRequest)
class MeowCreditRedeemRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'redeem_no', 'user', 'amount', 'status', 'redeem_method', 'reviewed_by', 'created_at', 'updated_at')
    list_filter = ('status', 'redeem_method', 'created_at')
    search_fields = ('redeem_no', 'user__email', 'redeem_method', 'reject_reason')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at', 'reviewed_at')
    autocomplete_fields = ('user', 'reviewed_by')
    actions = ('approve_selected_redeem_requests', 'reject_selected_redeem_requests_and_refund')

    @admin.action(description='Approve selected redeem requests')
    def approve_selected_redeem_requests(self, request, queryset):
        approved = 0
        skipped = 0
        for redeem_request in queryset:
            try:
                MeowCreditService.approve_redeem_request(redeem_request, request.user)
            except ValidationError:
                skipped += 1
            else:
                approved += 1
        self.message_user(request, f'Meow Credit redeem approval completed: approved={approved}, skipped={skipped}.')

    @admin.action(description='Reject selected redeem requests and refund credits')
    def reject_selected_redeem_requests_and_refund(self, request, queryset):
        rejected = 0
        skipped = 0
        for redeem_request in queryset:
            try:
                MeowCreditService.reject_redeem_request(redeem_request, request.user, 'Rejected by admin')
            except ValidationError:
                skipped += 1
            else:
                rejected += 1
        self.message_user(request, f'Meow Credit redeem rejection completed: rejected={rejected}, skipped={skipped}.')


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


@admin.register(DailyLoginReward)
class DailyLoginRewardAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'reward_date', 'points_amount', 'created_at')
    list_filter = ('reward_date', 'created_at')
    search_fields = ('user__email',)
    ordering = ('-reward_date', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('user', 'ledger_entry')


@admin.register(MeowPointPurchase)
class MeowPointPurchaseAdmin(admin.ModelAdmin):
    list_display = ('id', 'order_no', 'user', 'package_code_snapshot', 'total_points', 'price_amount', 'status', 'created_at')
    list_filter = ('status', 'price_currency', 'created_at')
    search_fields = ('order_no', 'user__email', 'package_code_snapshot', 'package_name_snapshot')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at', 'paid_at', 'credited_at')
    autocomplete_fields = ('user', 'package', 'payment_order')


@admin.register(Gift)
class GiftAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'points_price', 'is_active', 'sort_order')
    list_filter = ('is_active',)
    search_fields = ('code', 'name')
    ordering = ('sort_order', 'id')


@admin.register(GiftTransaction)
class GiftTransactionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'sender', 'receiver', 'drama_series', 'target_type', 'target_id', 'payment_method',
        'amount', 'points_amount', 'credits_amount', 'status', 'created_at',
    )
    list_filter = ('payment_method', 'status', 'target_type', 'created_at')
    search_fields = ('sender__email', 'receiver__email', 'gift_name_snapshot')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)
    autocomplete_fields = (
        'sender', 'receiver', 'stream', 'video', 'drama_series', 'gift', 'ledger_entry', 'credit_ledger_entry',
        'sender_point_ledger', 'receiver_point_ledger', 'sender_credit_ledger', 'receiver_credit_ledger',
    )


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


@admin.register(SellerApplication)
class SellerApplicationAdmin(admin.ModelAdmin):
    list_display = ('user', 'store_name', 'business_type', 'status', 'submitted_at', 'reviewed_at')
    list_filter = ('status', 'business_type', 'submitted_at', 'reviewed_at')
    search_fields = ('user__email', 'store_name', 'contact_email', 'contact_phone')
    ordering = ('-submitted_at', '-id')
    readonly_fields = ('status', 'reviewed_by', 'submitted_at', 'reviewed_at', 'created_at', 'updated_at')
    autocomplete_fields = ('user', 'reviewed_by')
    actions = ('approve_applications',)

    @admin.action(description='Approve selected seller applications')
    def approve_applications(self, request, queryset):
        approved = 0
        skipped = 0
        for application in queryset:
            try:
                approve_seller_application(application, reviewer=request.user)
            except ValueError:
                skipped += 1
            else:
                approved += 1
        self.message_user(request, f'Seller application approval completed: approved={approved}, skipped={skipped}.')

    def save_model(self, request, obj, form, change):
        original_status = None
        if change and obj.pk:
            original_status = SellerApplication.objects.filter(pk=obj.pk).values_list('status', flat=True).first()

        manual_approval = (
            change
            and original_status != SellerApplication.STATUS_APPROVED
            and obj.status == SellerApplication.STATUS_APPROVED
        )
        if manual_approval:
            obj.status = original_status
            super().save_model(request, obj, form, change)
            approve_seller_application(obj, reviewer=request.user)
            return

        super().save_model(request, obj, form, change)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'title',
        'slug',
        'store',
        'price_amount',
        'price_currency',
        'meow_points_price',
        'meow_credit_price',
        'stock_quantity',
        'status',
        'created_at',
        'updated_at',
    )
    list_filter = ('status', 'price_currency', 'category', 'created_at')
    search_fields = ('title', 'slug', 'store__name', 'store__slug', 'store__owner__email')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('store', 'category')


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'slug', 'is_active', 'sort_order', 'created_at', 'updated_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'slug')
    ordering = ('sort_order', 'id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ShopBanner)
class ShopBannerAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'is_active', 'sort_order', 'target_url', 'created_at', 'updated_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('title', 'subtitle', 'target_url')
    ordering = ('sort_order', '-id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ProductOrder)
class ProductOrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_no', 'buyer', 'seller_store', 'status', 'payment_method', 'payment_asset',
        'total_amount_snapshot', 'platform_fee_amount', 'seller_receivable_amount', 'created_at',
    )
    list_filter = ('status', 'payment_method', 'payment_asset', 'created_at')
    search_fields = ('order_no', 'buyer__email', 'seller_store__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(SellerPayout)
class SellerPayoutAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'product_order', 'seller_store', 'asset_type', 'gross_amount', 'platform_fee_amount', 'net_amount', 'status', 'paid_at'
    )
    list_filter = ('status', 'asset_type', 'created_at')
    search_fields = ('product_order__order_no', 'seller_store__name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(UserAssetBalance)
class UserAssetBalanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'asset_type', 'balance', 'updated_at')
    list_filter = ('asset_type',)
    search_fields = ('user__email',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(UserAssetTransaction)
class UserAssetTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'asset_type', 'direction', 'amount', 'biz_type', 'order_no', 'created_at')
    list_filter = ('asset_type', 'direction', 'biz_type')
    search_fields = ('user__email', 'order_no')
    readonly_fields = ('created_at',)


@admin.register(PlatformAssetLedger)
class PlatformAssetLedgerAdmin(admin.ModelAdmin):
    list_display = ('id', 'asset_type', 'direction', 'amount', 'biz_type', 'order_no', 'created_at')
    list_filter = ('asset_type', 'direction', 'biz_type')
    search_fields = ('order_no',)
    readonly_fields = ('created_at',)


@admin.register(SavedProduct)
class SavedProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'product', 'created_at')
    list_filter = ('created_at', 'product__status')
    search_fields = ('user__email', 'product__title')
    ordering = ('-created_at', '-id')
    readonly_fields = ('created_at',)


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
    list_display = (
        'id',
        'code',
        'name',
        'price_lbc',
        'base_price_amount',
        'base_price_asset',
        'allow_blockchain_payment',
        'allow_meow_points_payment',
        'allow_meow_credit_payment',
        'duration_days',
        'is_active',
        'sort_order',
    )
    list_filter = ('is_active', 'code')
    search_fields = ('code', 'name', 'description')
    ordering = ('sort_order', 'id')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(PaymentAssetRate)
class PaymentAssetRateAdmin(admin.ModelAdmin):
    list_display = ('asset_code', 'display_name', 'exchange_rate', 'is_active', 'sort_order', 'updated_at')
    search_fields = ('asset_code', 'display_name')
    list_filter = ('is_active',)
    ordering = ('sort_order', 'asset_code')
    readonly_fields = ('created_at', 'updated_at')

    def get_readonly_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj is not None:
            fields.append('asset_code')
        return tuple(fields)


@admin.register(ManualMembershipPayment)
class ManualMembershipPaymentAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'txid',
        'user',
        'plan',
        'status',
        'expected_amount_lbc',
        'actual_amount_lbc',
        'pay_to_address',
        'confirmations',
        'payment_order',
        'membership',
        'created_at',
        'verified_at',
    )
    list_filter = ('status', 'plan__code', 'created_at', 'verified_at')
    search_fields = (
        'txid',
        'pay_to_address',
        'user__email',
        'plan__code',
        'plan__name',
        'payment_order__order_no',
    )
    ordering = ('-created_at', '-id')
    readonly_fields = ('raw_tx', 'payment_order', 'membership', 'created_at', 'updated_at')
    autocomplete_fields = ('user', 'plan')


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
