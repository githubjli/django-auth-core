from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.conf import settings
from django.db import models


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

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    def __str__(self) -> str:
        return self.email


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
    file = models.FileField(upload_to='videos/')
    thumbnail = models.FileField(upload_to='thumbnails/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
