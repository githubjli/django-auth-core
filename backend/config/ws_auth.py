from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

User = get_user_model()


@database_sync_to_async
def get_user_by_id(user_id: int):
    try:
        return User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return AnonymousUser()


class QueryStringJWTAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        query_string = scope.get('query_string', b'').decode()
        token = parse_qs(query_string).get('token', [None])[0]
        if not token:
            scope['user'] = AnonymousUser()
            return await self.app(scope, receive, send)
        try:
            validated = AccessToken(token)
            user_id = validated.get('user_id')
            if not user_id:
                scope['user'] = AnonymousUser()
            else:
                scope['user'] = await get_user_by_id(int(user_id))
        except (TokenError, ValueError, TypeError):
            scope['user'] = AnonymousUser()
        return await self.app(scope, receive, send)
