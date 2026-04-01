from django.urls import re_path

from apps.accounts.consumers import LiveChatConsumer

websocket_urlpatterns = [
    re_path(r'^ws/live/(?P<live_id>\d+)/chat/$', LiveChatConsumer.as_asgi()),
]
