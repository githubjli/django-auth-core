from django.urls import path

from apps.accounts.views import ChannelSubscriptionAPIView

urlpatterns = [
    path('<int:pk>/subscribe/', ChannelSubscriptionAPIView.as_view(), name='channel-subscribe'),
]
