from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/account/', include('apps.accounts.account_urls')),
    path('api/admin/', include('apps.accounts.admin_urls')),
    path('api/videos/', include('apps.accounts.video_urls')),
    path('api/store/', include('apps.accounts.store_urls')),
    path('api/stores/', include('apps.accounts.public_store_urls')),
    path('api/channels/', include('apps.accounts.channel_urls')),
    path('api/creators/', include('apps.accounts.creators_urls')),
    path('api/billing/', include('apps.accounts.billing_urls')),
    path('api/membership/', include('apps.accounts.membership_urls')),
    path('api/live/', include('apps.accounts.live_urls')),
    path('api/public/categories/', include('apps.accounts.public_category_urls')),
    path('api/public/videos/', include('apps.accounts.public_video_urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
