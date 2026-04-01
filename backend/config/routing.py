from channels.routing import URLRouter

from apps.accounts.ws_urls import websocket_urlpatterns

application = URLRouter(websocket_urlpatterns)
