from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import LiveChatMessage, LiveChatRoom, LiveStream, Product
from apps.accounts.serializers import LiveChatMessageCreateSerializer, LiveChatMessageSerializer


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
        room = await self._get_room(stream)
        if not room.is_enabled:
            await self.send_json({'type': 'error', 'detail': 'Chat is disabled for this stream.'})
            return
        if room.slow_mode_seconds > 0:
            limited = await self._is_slow_mode_limited(room, user.id, room.slow_mode_seconds)
            if limited:
                await self.send_json({'type': 'error', 'detail': 'Slow mode is enabled. Please wait before sending again.'})
                return

        serializer = LiveChatMessageCreateSerializer(data=content.get('data', {}))
        if not serializer.is_valid():
            await self.send_json({'type': 'error', 'errors': serializer.errors})
            return

        message = await self._create_message(room.id, user.id, serializer.validated_data)
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
    def _is_slow_mode_limited(self, room, user_id, slow_mode_seconds: int) -> bool:
        cutoff = timezone.now() - timedelta(seconds=slow_mode_seconds)
        return LiveChatMessage.objects.filter(
            room=room,
            user_id=user_id,
            created_at__gte=cutoff,
            is_deleted=False,
        ).exists()

    @database_sync_to_async
    def _create_message(self, room_id: int, user_id: int, validated_data: dict):
        reply_to = None
        reply_to_id = validated_data.get('reply_to_id')
        if reply_to_id:
            reply_to = LiveChatMessage.objects.filter(pk=reply_to_id, room_id=room_id).first()

        product = None
        if validated_data.get('message_type') == LiveChatMessage.TYPE_PRODUCT:
            product_id = validated_data.get('product_id')
            if product_id:
                product = Product.objects.filter(pk=product_id, status=Product.STATUS_ACTIVE).first()

        return LiveChatMessage.objects.create(
            room_id=room_id,
            user_id=user_id,
            message_type=validated_data.get('message_type', LiveChatMessage.TYPE_TEXT),
            content=validated_data.get('content', ''),
            reply_to=reply_to,
            product=product,
        )

    @database_sync_to_async
    def _serialize_message(self, message):
        message = LiveChatMessage.objects.select_related('room__stream', 'user', 'product', 'product__store').get(pk=message.pk)
        return LiveChatMessageSerializer(message).data
