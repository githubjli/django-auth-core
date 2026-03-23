from django.urls import path

from apps.accounts.views import (
    AdminUserActivationAPIView,
    AdminUserDetailAPIView,
    AdminUserListAPIView,
    AdminVideoDetailAPIView,
    AdminVideoListAPIView,
)

urlpatterns = [
    path('users/', AdminUserListAPIView.as_view(), name='admin-user-list'),
    path('users/<int:pk>/', AdminUserDetailAPIView.as_view(), name='admin-user-detail'),
    path(
        'users/<int:pk>/activate/',
        AdminUserActivationAPIView.as_view(active=True),
        name='admin-user-activate',
    ),
    path(
        'users/<int:pk>/deactivate/',
        AdminUserActivationAPIView.as_view(active=False),
        name='admin-user-deactivate',
    ),
    path('videos/', AdminVideoListAPIView.as_view(), name='admin-video-list'),
    path('videos/<int:pk>/', AdminVideoDetailAPIView.as_view(), name='admin-video-detail'),
]
