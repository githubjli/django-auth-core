"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_asgi_app = get_asgi_application()
try:
    from channels.routing import ProtocolTypeRouter
    from config.routing import application as websocket_application
    from config.ws_auth import QueryStringJWTAuthMiddleware
except ModuleNotFoundError:
    application = django_asgi_app
else:
    application = ProtocolTypeRouter({
        'http': django_asgi_app,
        'websocket': QueryStringJWTAuthMiddleware(websocket_application),
    })
