import secrets
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models

from apps.accounts.constants import TOKEN_SYMBOL



def generate_stream_key() -> str:
    return secrets.token_urlsafe(24)

class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError('Email must be provided')

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault('is_staff', False)
        extra_fields.setdefault('is_superuser', False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email: str, password: str, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    WALLET_LINKED = 'linked'
    WALLET_UNLINKED = 'unlinked'
    WALLET_PENDING = 'pending'
    WALLET_LINK_STATUS_CHOICES = [
        (WALLET_LINKED, 'Linked'),
        (WALLET_UNLINKED, 'Unlinked'),
        (WALLET_PENDING, 'Pending'),
    ]

    username = None
    email = models.EmailField(unique=True)
    subscriber_count = models.PositiveIntegerField(default=0)
    avatar = models.FileField(upload_to='avatars/', blank=True)
    bio = models.TextField(blank=True)
    language = models.CharField(max_length=10, default='en-US')
    theme = models.CharField(max_length=10, default='system')
    timezone = models.CharField(max_length=64, blank=True)
    is_creator = models.BooleanField(default=False)
    linked_wallet_id = models.CharField(max_length=128, blank=True, default='')
    primary_user_address = models.CharField(max_length=128, blank=True, default='')
    wallet_link_status = models.CharField(max_length=24, choices=WALLET_LINK_STATUS_CHOICES, blank=True, default='')
    linked_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    def __str__(self) -> str:
        return self.email

    @property
    def display_name(self) -> str:
        full_name = f'{self.first_name} {self.last_name}'.strip()
        return full_name or self.email


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    show_on_homepage = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'name']

    def __str__(self) -> str:
        return self.name


class Video(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_FLAGGED = 'flagged'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_FLAGGED, 'Flagged'),
        (STATUS_ARCHIVED, 'Archived'),
    ]

    VISIBILITY_PUBLIC = 'public'
    VISIBILITY_PRIVATE = 'private'
    VISIBILITY_CHOICES = [
        (VISIBILITY_PUBLIC, 'Public'),
        (VISIBILITY_PRIVATE, 'Private'),
    ]

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='videos',
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='videos',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default=VISIBILITY_PUBLIC)
    like_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)
    file = models.FileField(upload_to='videos/')
    thumbnail = models.FileField(upload_to='thumbnails/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return self.title

    @property
    def category_name(self) -> str:
        if not self.category:
            return ''
        return self.category.name

    @property
    def category_slug(self) -> str:
        if not self.category:
            return ''
        return self.category.slug


class DramaSeries(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_ARCHIVED = 'archived'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_ARCHIVED, 'Archived'),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    cover = models.FileField(upload_to='dramas/covers/', blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='drama_series',
    )
    tags = models.JSONField(default=list, blank=True)
    total_episodes = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PUBLISHED)
    is_active = models.BooleanField(default=True)
    view_count = models.PositiveIntegerField(default=0)
    favorite_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return self.title


class DramaEpisode(models.Model):
    UNLOCK_FREE = 'free'
    UNLOCK_MEOW_POINTS = 'meow_points'
    UNLOCK_MEMBERSHIP = 'membership'
    UNLOCK_AD_REWARD = 'ad_reward'
    UNLOCK_TYPE_CHOICES = [
        (UNLOCK_FREE, 'Free'),
        (UNLOCK_MEOW_POINTS, 'Meow Points'),
        (UNLOCK_MEMBERSHIP, 'Membership'),
        (UNLOCK_AD_REWARD, 'Ad Reward'),
    ]

    series = models.ForeignKey(
        DramaSeries,
        on_delete=models.CASCADE,
        related_name='episodes',
    )
    episode_no = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    video_file = models.FileField(upload_to='dramas/videos/', blank=True)
    video_url = models.URLField(blank=True)
    hls_url = models.URLField(blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    is_free = models.BooleanField(default=False)
    unlock_type = models.CharField(max_length=20, choices=UNLOCK_TYPE_CHOICES, default=UNLOCK_MEOW_POINTS)
    meow_points_price = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'episode_no', 'id']
        constraints = [
            models.UniqueConstraint(fields=['series', 'episode_no'], name='unique_drama_episode_no_per_series'),
        ]

    def __str__(self) -> str:
        return f'{self.series_id} - Ep {self.episode_no}: {self.title}'


class DramaWatchProgress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='drama_watch_progress',
    )
    series = models.ForeignKey(
        DramaSeries,
        on_delete=models.CASCADE,
        related_name='watch_progress',
    )
    episode = models.ForeignKey(
        DramaEpisode,
        on_delete=models.CASCADE,
        related_name='watch_progress',
    )
    progress_seconds = models.PositiveIntegerField(default=0)
    completed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['user', 'series'], name='unique_drama_progress_per_user_series'),
        ]


class DramaFavorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='drama_favorites',
    )
    series = models.ForeignKey(
        DramaSeries,
        on_delete=models.CASCADE,
        related_name='favorites',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['user', 'series'], name='unique_drama_favorite_per_user_series'),
        ]


class VideoView(models.Model):
    video = models.ForeignKey(
        Video,
        on_delete=models.CASCADE,
        related_name='views',
    )
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='video_views',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class VideoLike(models.Model):
    video = models.ForeignKey(
        Video,
        on_delete=models.CASCADE,
        related_name='likes',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='liked_videos',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['video', 'user'], name='unique_video_like_per_user')
        ]


class ChannelSubscription(models.Model):
    channel = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions_received',
    )
    subscriber = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='channel_subscriptions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['channel', 'subscriber'],
                name='unique_channel_subscription_per_user',
            ),
        ]


class VideoComment(models.Model):
    video = models.ForeignKey(
        Video,
        on_delete=models.CASCADE,
        related_name='comments',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='video_comments',
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies',
    )
    content = models.TextField()
    like_count = models.PositiveIntegerField(default=0)
    reply_count = models.PositiveIntegerField(default=0)
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']


class CommentLike(models.Model):
    comment = models.ForeignKey(
        VideoComment,
        on_delete=models.CASCADE,
        related_name='likes',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='liked_comments',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['comment', 'user'], name='unique_comment_like_per_user')
        ]


class SellerStore(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='seller_store',
    )
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    logo = models.FileField(upload_to='stores/logos/', blank=True)
    banner = models.FileField(upload_to='stores/banners/', blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    store = models.ForeignKey(
        SellerStore,
        on_delete=models.CASCADE,
        related_name='products',
    )
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True)
    cover_image = models.FileField(upload_to='stores/products/', blank=True)
    price_amount = models.DecimalField(max_digits=12, decimal_places=2)
    price_currency = models.CharField(max_length=3, default='USD')
    stock_quantity = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['store', 'slug'], name='unique_product_slug_per_store')
        ]

    def __str__(self) -> str:
        return self.title


class UserShippingAddress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='shipping_addresses',
    )
    receiver_name = models.CharField(max_length=255)
    phone = models.CharField(max_length=64, blank=True, default='')
    country = models.CharField(max_length=120)
    province = models.CharField(max_length=120, blank=True, default='')
    city = models.CharField(max_length=120, blank=True, default='')
    district = models.CharField(max_length=120, blank=True, default='')
    street_address = models.TextField()
    postal_code = models.CharField(max_length=24, blank=True, default='')
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-is_default', '-updated_at', '-id']


class ProductOrder(models.Model):
    STATUS_PENDING_PAYMENT = 'pending_payment'
    STATUS_PAID = 'paid'
    STATUS_SHIPPING = 'shipping'
    STATUS_COMPLETED = 'completed'
    STATUS_SETTLED = 'settled'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING_PAYMENT, 'Pending Payment'),
        (STATUS_PAID, 'Paid'),
        (STATUS_SHIPPING, 'Shipping'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_SETTLED, 'Settled'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    order_no = models.CharField(max_length=64, unique=True)
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='product_orders',
    )
    seller_store = models.ForeignKey(
        SellerStore,
        on_delete=models.CASCADE,
        related_name='product_orders',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='product_orders',
    )
    product_title_snapshot = models.CharField(max_length=255)
    product_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default=TOKEN_SYMBOL)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING_PAYMENT)
    shipping_address_snapshot = models.JSONField(default=dict)
    payment_order = models.OneToOneField(
        'PaymentOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='linked_product_order',
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    stock_locked_at = models.DateTimeField(null=True, blank=True)
    stock_released_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=64, blank=True, default='')
    expires_at = models.DateTimeField(null=True, blank=True)
    shipped_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']


class ProductShipment(models.Model):
    product_order = models.OneToOneField(
        ProductOrder,
        on_delete=models.CASCADE,
        related_name='shipment',
    )
    carrier = models.CharField(max_length=255)
    tracking_number = models.CharField(max_length=255)
    tracking_url = models.URLField(blank=True, default='')
    shipped_note = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_product_shipments',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']


class SellerPayout(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PAID = 'paid'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PAID, 'Paid'),
        (STATUS_FAILED, 'Failed'),
    ]

    product_order = models.OneToOneField(
        ProductOrder,
        on_delete=models.CASCADE,
        related_name='seller_payout',
    )
    seller_store = models.ForeignKey(
        SellerStore,
        on_delete=models.CASCADE,
        related_name='seller_payouts',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default=TOKEN_SYMBOL)
    payout_address = models.CharField(max_length=255, blank=True, default='')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING)
    txid = models.CharField(max_length=255, blank=True, default='')
    note = models.TextField(blank=True, default='')
    failure_note = models.CharField(max_length=255, blank=True, default='')
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']


class SellerPayoutAddress(models.Model):
    seller_store = models.ForeignKey(
        SellerStore,
        on_delete=models.CASCADE,
        related_name='payout_addresses',
    )
    blockchain = models.CharField(max_length=24, default='LTT')
    token_symbol = models.CharField(max_length=24, default=TOKEN_SYMBOL)
    address = models.CharField(max_length=255)
    label = models.CharField(max_length=255, blank=True, default='')
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-is_default', '-updated_at', '-id']


class ProductRefundRequest(models.Model):
    STATUS_REQUESTED = 'requested'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_REFUNDED = 'refunded'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_REQUESTED, 'Requested'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_REFUNDED, 'Refunded'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
    ACTIVE_STATUSES = {STATUS_REQUESTED, STATUS_APPROVED}

    product_order = models.ForeignKey(
        ProductOrder,
        on_delete=models.CASCADE,
        related_name='refund_requests',
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='product_refund_requests',
    )
    reason = models.TextField()
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_REQUESTED)
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default=TOKEN_SYMBOL)
    admin_note = models.TextField(blank=True, default='')
    seller_note = models.TextField(blank=True, default='')
    refund_txid = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']


class LiveStream(models.Model):
    STATUS_IDLE = 'idle'
    STATUS_LIVE = 'live'
    STATUS_ENDED = 'ended'
    STATUS_CHOICES = [
        (STATUS_IDLE, 'Idle'),
        (STATUS_LIVE, 'Live'),
        (STATUS_ENDED, 'Ended'),
    ]
    VISIBILITY_PUBLIC = 'public'
    VISIBILITY_UNLISTED = 'unlisted'
    VISIBILITY_PRIVATE = 'private'
    VISIBILITY_CHOICES = [
        (VISIBILITY_PUBLIC, 'Public'),
        (VISIBILITY_UNLISTED, 'Unlisted'),
        (VISIBILITY_PRIVATE, 'Private'),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='live_streams',
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    payment_address = models.TextField(blank=True)
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='live_streams',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IDLE)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default=VISIBILITY_PUBLIC)
    stream_key = models.CharField(max_length=255, unique=True, default=generate_stream_key)
    viewer_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self) -> str:
        return self.title


class LiveStreamProduct(models.Model):
    stream = models.ForeignKey(
        LiveStream,
        on_delete=models.CASCADE,
        related_name='product_bindings',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name='live_stream_bindings',
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_pinned = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', '-is_pinned', '-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['stream', 'product'],
                condition=models.Q(is_active=True),
                name='unique_active_stream_product_binding',
            ),
        ]


class LiveChatRoom(models.Model):
    stream = models.OneToOneField(
        LiveStream,
        on_delete=models.CASCADE,
        related_name='chat_room',
    )
    is_enabled = models.BooleanField(default=True)
    slow_mode_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']


class LiveChatMessage(models.Model):
    TYPE_TEXT = 'text'
    TYPE_SYSTEM = 'system'
    TYPE_PRODUCT = 'product'
    TYPE_PAYMENT = 'payment'
    MESSAGE_TYPE_CHOICES = [
        (TYPE_TEXT, 'Text'),
        (TYPE_SYSTEM, 'System'),
        (TYPE_PRODUCT, 'Product'),
        (TYPE_PAYMENT, 'Payment'),
    ]

    room = models.ForeignKey(
        LiveChatRoom,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='live_chat_messages',
    )
    message_type = models.CharField(max_length=20, choices=MESSAGE_TYPE_CHOICES, default=TYPE_TEXT)
    content = models.TextField(blank=True)
    is_deleted = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    reply_to = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='replies',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chat_messages',
    )
    payment_reference = models.CharField(max_length=255, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']


class StreamPaymentMethod(models.Model):
    TYPE_WATCH_QR = 'watch_qr'
    TYPE_PAY_QR = 'pay_qr'
    TYPE_PAID_PROGRAM_QR = 'paid_program_qr'
    TYPE_CRYPTO_ADDRESS = 'crypto_address'
    METHOD_TYPE_CHOICES = [
        (TYPE_WATCH_QR, 'Watch QR'),
        (TYPE_PAY_QR, 'Pay QR'),
        (TYPE_PAID_PROGRAM_QR, 'Paid Programming QR'),
        (TYPE_CRYPTO_ADDRESS, 'Crypto Address'),
    ]

    stream = models.ForeignKey(
        LiveStream,
        on_delete=models.CASCADE,
        related_name='payment_methods',
    )
    method_type = models.CharField(max_length=32, choices=METHOD_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    qr_image = models.FileField(upload_to='live/payment_qr/', null=True, blank=True)
    qr_text = models.TextField(null=True, blank=True)
    wallet_address = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['sort_order', '-created_at', '-id']


class PaymentOrder(models.Model):
    TYPE_TIP = 'tip'
    TYPE_PRODUCT = 'product'
    TYPE_PAID_PROGRAM = 'paid_program'
    TYPE_MEMBERSHIP = 'membership'
    ORDER_TYPE_CHOICES = [
        (TYPE_TIP, 'Tip'),
        (TYPE_PRODUCT, 'Product'),
        (TYPE_PAID_PROGRAM, 'Paid Program'),
        (TYPE_MEMBERSHIP, 'Membership'),
    ]

    STATUS_PENDING = 'pending'
    STATUS_PAID = 'paid'
    STATUS_EXPIRED = 'expired'
    STATUS_FAILED = 'failed'
    STATUS_UNDERPAID = 'underpaid'
    STATUS_OVERPAID = 'overpaid'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_PAID, 'Paid'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_UNDERPAID, 'Underpaid'),
        (STATUS_OVERPAID, 'Overpaid'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_orders',
    )
    stream = models.ForeignKey(
        LiveStream,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_orders',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_orders',
    )
    payment_method = models.ForeignKey(
        StreamPaymentMethod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_orders',
    )
    order_type = models.CharField(max_length=24, choices=ORDER_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='USD')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING)
    client_request_id = models.CharField(max_length=128, blank=True, default='')
    external_reference = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_orders_marked_paid',
    )
    paid_note = models.TextField(blank=True, default='')
    order_no = models.CharField(max_length=64, blank=True, default='')
    target_type = models.CharField(max_length=64, blank=True, default='')
    target_id = models.PositiveIntegerField(null=True, blank=True)
    plan_code_snapshot = models.CharField(max_length=64, blank=True, default='')
    plan_name_snapshot = models.CharField(max_length=255, blank=True, default='')
    expected_amount_lbc = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    actual_amount_lbc = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    pay_to_address = models.CharField(max_length=128, blank=True, default='')
    wallet_address = models.ForeignKey(
        'WalletAddress',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_orders',
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    txid = models.CharField(max_length=128, blank=True, default='')
    confirmations = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'stream', 'client_request_id'],
                condition=~models.Q(client_request_id=''),
                name='unique_payment_order_request_id_per_user_stream',
            ),
            models.UniqueConstraint(
                fields=['order_no'],
                condition=~models.Q(order_no=''),
                name='unique_payment_order_no_when_present',
            ),
        ]


class MembershipPlan(models.Model):
    CODE_MONTHLY = 'monthly'
    CODE_QUARTERLY = 'quarterly'
    CODE_YEARLY = 'yearly'
    CODE_CHOICES = [
        (CODE_MONTHLY, 'Monthly'),
        (CODE_QUARTERLY, 'Quarterly'),
        (CODE_YEARLY, 'Yearly'),
    ]

    code = models.CharField(max_length=32, choices=CODE_CHOICES, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    price_lbc = models.DecimalField(max_digits=18, decimal_places=8)
    duration_days = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self) -> str:
        return self.name


class WalletAddress(models.Model):
    USAGE_MEMBERSHIP = 'membership'
    USAGE_PRODUCT = 'product'
    USAGE_TIP = 'tip'
    USAGE_DEPOSIT = 'deposit'
    USAGE_GENERAL = 'general'
    USAGE_TYPE_CHOICES = [
        (USAGE_MEMBERSHIP, 'Membership'),
        (USAGE_PRODUCT, 'Product'),
        (USAGE_TIP, 'Tip'),
        (USAGE_DEPOSIT, 'Deposit'),
        (USAGE_GENERAL, 'General'),
    ]

    STATUS_AVAILABLE = 'available'
    STATUS_ASSIGNED = 'assigned'
    STATUS_RETIRED = 'retired'
    STATUS_CHOICES = [
        (STATUS_AVAILABLE, 'Available'),
        (STATUS_ASSIGNED, 'Assigned'),
        (STATUS_RETIRED, 'Retired'),
    ]

    address = models.CharField(max_length=128, unique=True)
    label = models.CharField(max_length=255, blank=True, default='')
    wallet_id = models.CharField(max_length=128, blank=True, default='')
    account_id = models.CharField(max_length=128, blank=True, default='')
    usage_type = models.CharField(max_length=24, choices=USAGE_TYPE_CHOICES, default=USAGE_GENERAL)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_AVAILABLE)
    assigned_order = models.ForeignKey(
        'PaymentOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_wallet_addresses',
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-id']
        constraints = [
            models.UniqueConstraint(
                fields=['assigned_order'],
                condition=models.Q(assigned_order__isnull=False),
                name='unique_wallet_address_assigned_order',
            ),
        ]

    def __str__(self) -> str:
        return self.address


class ChainReceipt(models.Model):
    CURRENCY_LBC = 'LBC'
    CURRENCY_CHOICES = [
        (CURRENCY_LBC, TOKEN_SYMBOL),
    ]

    MATCH_UNMATCHED = 'unmatched'
    MATCH_MATCHED = 'matched'
    MATCH_IGNORED = 'ignored'
    MATCH_STATUS_CHOICES = [
        (MATCH_UNMATCHED, 'Unmatched'),
        (MATCH_MATCHED, 'Matched'),
        (MATCH_IGNORED, 'Ignored'),
    ]

    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default=CURRENCY_LBC)
    wallet_id = models.CharField(max_length=128, blank=True, default='')
    address = models.CharField(max_length=128)
    txid = models.CharField(max_length=128)
    vout = models.PositiveIntegerField(null=True, blank=True)
    amount_lbc = models.DecimalField(max_digits=18, decimal_places=8)
    block_height = models.PositiveBigIntegerField(null=True, blank=True)
    confirmations = models.PositiveIntegerField(default=0)
    seen_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    raw_payload = models.JSONField(null=True, blank=True)
    matched_order = models.ForeignKey(
        'PaymentOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='chain_receipts',
    )
    match_status = models.CharField(max_length=24, choices=MATCH_STATUS_CHOICES, default=MATCH_UNMATCHED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-seen_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['currency', 'txid', 'vout'], name='unique_chain_receipt_output'),
        ]
        indexes = [
            models.Index(fields=['address', 'seen_at'], name='chain_receipt_address_seen_idx'),
            models.Index(fields=['match_status', 'seen_at'], name='chain_receipt_match_seen_idx'),
        ]

    def __str__(self) -> str:
        return f'{self.currency}:{self.txid}'


class OrderPayment(models.Model):
    PAYMENT_PENDING = 'pending'
    PAYMENT_CONFIRMED = 'confirmed'
    PAYMENT_FAILED = 'failed'
    PAYMENT_STATUS_CHOICES = [
        (PAYMENT_PENDING, 'Pending'),
        (PAYMENT_CONFIRMED, 'Confirmed'),
        (PAYMENT_FAILED, 'Failed'),
    ]

    order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.CASCADE,
        related_name='payments',
    )
    receipt = models.ForeignKey(
        ChainReceipt,
        on_delete=models.CASCADE,
        related_name='order_payments',
    )
    txid = models.CharField(max_length=128)
    amount_lbc = models.DecimalField(max_digits=18, decimal_places=8)
    confirmations = models.PositiveIntegerField(default=0)
    payment_status = models.CharField(max_length=24, choices=PAYMENT_STATUS_CHOICES, default=PAYMENT_PENDING)
    matched_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-matched_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['order', 'receipt'], name='unique_order_receipt_payment'),
        ]
        indexes = [
            models.Index(fields=['order', 'payment_status'], name='order_payment_order_status_idx'),
            models.Index(fields=['txid'], name='order_payment_txid_idx'),
        ]


class UserMembership(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_EXPIRED = 'expired'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='user_memberships',
    )
    source_order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.PROTECT,
        related_name='user_memberships',
    )
    plan = models.ForeignKey(
        MembershipPlan,
        on_delete=models.PROTECT,
        related_name='memberships',
    )
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-ends_at', '-id']
        indexes = [
            models.Index(fields=['user', 'status', 'ends_at'], name='membership_user_status_end_idx'),
            models.Index(fields=['starts_at', 'ends_at'], name='membership_valid_window_idx'),
        ]


class BillingPlan(models.Model):
    INTERVAL_MONTH = 'month'
    INTERVAL_YEAR = 'year'
    INTERVAL_CHOICES = [
        (INTERVAL_MONTH, 'Monthly'),
        (INTERVAL_YEAR, 'Yearly'),
    ]

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    billing_interval = models.CharField(max_length=16, choices=INTERVAL_CHOICES, default=INTERVAL_MONTH)
    price_amount = models.DecimalField(max_digits=12, decimal_places=2)
    price_currency = models.CharField(max_length=10, default='USD')
    wallet_address = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['price_amount', 'id']

    def __str__(self) -> str:
        return f'{self.name} ({self.billing_interval})'


class BillingSubscription(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_CANCELLED = 'cancelled'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='billing_subscriptions',
    )
    plan = models.ForeignKey(
        BillingPlan,
        on_delete=models.PROTECT,
        related_name='subscriptions',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    auto_renew = models.BooleanField(default=True)
    started_at = models.DateTimeField(auto_now_add=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']


class MeowPointWallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='meow_point_wallet',
    )
    balance = models.IntegerField(default=0)
    total_earned = models.PositiveIntegerField(default=0)
    total_spent = models.PositiveIntegerField(default=0)
    total_purchased = models.PositiveIntegerField(default=0)
    total_bonus = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['-updated_at', '-id']


class MeowPointPackage(models.Model):
    STATUS_ACTIVE = 'active'
    STATUS_INACTIVE = 'inactive'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_INACTIVE, 'Inactive'),
    ]

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    points_amount = models.PositiveIntegerField(default=0)
    bonus_points = models.PositiveIntegerField(default=0)
    price_amount = models.DecimalField(max_digits=12, decimal_places=2)
    price_currency = models.CharField(max_length=16, default=TOKEN_SYMBOL)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    sort_order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ['sort_order', 'id']


class MeowPointLedger(models.Model):
    TYPE_PURCHASE = 'purchase'
    TYPE_BONUS = 'bonus'
    TYPE_REWARD = 'reward'
    TYPE_SPEND = 'spend'
    TYPE_REFUND = 'refund'
    TYPE_ADMIN_ADJUST = 'admin_adjust'
    ENTRY_TYPE_CHOICES = [
        (TYPE_PURCHASE, 'Purchase'),
        (TYPE_BONUS, 'Bonus'),
        (TYPE_REWARD, 'Reward'),
        (TYPE_SPEND, 'Spend'),
        (TYPE_REFUND, 'Refund'),
        (TYPE_ADMIN_ADJUST, 'Admin Adjust'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='meow_point_ledger_entries',
    )
    entry_type = models.CharField(max_length=24, choices=ENTRY_TYPE_CHOICES)
    amount = models.IntegerField()
    balance_before = models.IntegerField()
    balance_after = models.IntegerField()
    target_type = models.CharField(max_length=64, blank=True, default='')
    target_id = models.PositiveBigIntegerField(null=True, blank=True)
    payment_order = models.ForeignKey(
        PaymentOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='meow_point_ledger_entries',
    )
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
