from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from apps.accounts.models import LiveChatMessage, LiveChatRoom, LiveStream
from apps.accounts.serializers import LiveChatMessageCreateSerializer, LiveChatMessageSerializer
from apps.accounts.services import create_live_chat_message


class LiveChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.live_id = int(self.scope['url_route']['kwargs']['live_id'])
        self.group_name = f'live_chat_{self.live_id}'
        user = self.scope.get('user')
        stream = await self._get_stream()
        if stream is None or not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        if stream.visibility == LiveStream.VISIBILITY_PRIVATE and stream.owner_id != user.id:
            await self.close(code=4403)
            return
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        action = content.get('action')
        if action != 'post_message':
            await self.send_json({'type': 'error', 'detail': 'Unsupported action.'})
            return
        user = self.scope['user']
        stream = await self._get_stream()
        if stream is None:
            await self.send_json({'type': 'error', 'detail': 'Stream not found.'})
            return
        serializer = LiveChatMessageCreateSerializer(data=content.get('data', {}))
        if not serializer.is_valid():
            await self.send_json({'type': 'error', 'errors': serializer.errors})
            return

        message, error_text = await self._create_message(stream.id, user.id, serializer.validated_data)
        if message is None:
            await self.send_json({'type': 'error', 'detail': error_text})
            return
        payload = await self._serialize_message(message)
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'chat.message',
                'event': 'message_created',
                'message': payload,
            },
        )

    async def chat_message(self, event):
        await self.send_json({
            'type': event['event'],
            'message': event['message'],
        })

    @database_sync_to_async
    def _get_stream(self):
        try:
            return LiveStream.objects.select_related('owner').get(pk=self.live_id)
        except LiveStream.DoesNotExist:
            return None

    @database_sync_to_async
    def _get_room(self, stream):
        room, _ = LiveChatRoom.objects.get_or_create(stream=stream)
        return room

    @database_sync_to_async
    def _create_message(self, stream_id: int, user_id: int, validated_data: dict):
        try:
            stream = LiveStream.objects.select_related('owner').get(pk=stream_id)
            user = stream.owner.__class__.objects.get(pk=user_id)
            message = create_live_chat_message(stream=stream, user=user, validated_data=validated_data)
            return message, None
        except Exception as exc:
            return None, str(exc)

    @database_sync_to_async
    def _serialize_message(self, message):
        message = LiveChatMessage.objects.select_related('room__stream', 'user', 'product', 'product__store').get(pk=message.pk)
        return LiveChatMessageSerializer(message).data
