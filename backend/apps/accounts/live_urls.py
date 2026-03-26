from django.urls import path

from apps.accounts.views import (
    LiveStreamCreateAPIView,
    LiveStreamDetailAPIView,
    LiveStreamListAPIView,
    LiveStreamStatusDetailAPIView,
    LiveStreamStatusAPIView,
    LiveStreamUpdateAPIView,
)

urlpatterns = [
    path('', LiveStreamListAPIView.as_view(), name='live-stream-list'),
    path('create/', LiveStreamCreateAPIView.as_view(), name='live-stream-create'),
    path('<int:pk>/', LiveStreamDetailAPIView.as_view(), name='live-stream-detail'),
    path('<int:pk>/status/', LiveStreamStatusDetailAPIView.as_view(), name='live-stream-status'),
    path('<int:pk>/update/', LiveStreamUpdateAPIView.as_view(), name='live-stream-update'),
    path('<int:pk>/start/', LiveStreamStatusAPIView.as_view(new_status='live'), name='live-stream-start'),
    path('<int:pk>/end/', LiveStreamStatusAPIView.as_view(new_status='ended'), name='live-stream-end'),
]
