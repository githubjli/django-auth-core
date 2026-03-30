from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.accounts.models import (
    Category,
    ChannelSubscription,
    LiveStream,
    User,
    Video,
    VideoComment,
    VideoLike,
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
