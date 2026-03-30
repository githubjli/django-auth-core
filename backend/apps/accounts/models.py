import secrets
from django.conf import settings
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models




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
    username = None
    email = models.EmailField(unique=True)
    subscriber_count = models.PositiveIntegerField(default=0)
    avatar = models.FileField(upload_to='avatars/', blank=True)
    bio = models.TextField(blank=True)
    language = models.CharField(max_length=10, default='en-US')
    theme = models.CharField(max_length=10, default='system')
    timezone = models.CharField(max_length=64, blank=True)
    is_creator = models.BooleanField(default=False)

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
