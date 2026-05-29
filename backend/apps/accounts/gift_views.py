from asgiref.sync import async_to_sync
try:
    from channels.layers import get_channel_layer
except ModuleNotFoundError:  # pragma: no cover
    def get_channel_layer():
        return None
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
import logging
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.gift_serializers import ContentGiftSendSerializer, GiftSendSerializer, GiftSerializer, GiftTransactionSerializer
from apps.accounts.models import Gift, GiftTransaction, LiveStream, LiveChatMessage, LiveChatRoom
from apps.accounts.serializers import LiveChatMessageSerializer
from apps.accounts.services import GiftService


logger = logging.getLogger(__name__)


class GiftListAPIView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = GiftSerializer
    pagination_class = None

    def get_queryset(self):
        return Gift.objects.filter(is_active=True).order_by('sort_order', 'id')


class LiveGiftListAPIView(GiftListAPIView):
    def get_queryset(self):
        get_object_or_404(LiveStream, pk=self.kwargs['pk'])
        return super().get_queryset()


def _insufficient_balance_response(payment_method):
    return Response(
        {
            'code': 'insufficient_balance',
            'detail': 'Insufficient balance.',
            'payment_method': payment_method,
        },
        status=status.HTTP_400_BAD_REQUEST,
    )


def _is_insufficient_balance(exc):
    error_text = str(exc)
    return 'Insufficient Meow Points balance.' in error_text or 'Insufficient Meow Credit balance.' in error_text


def _broadcast_live_gift_message(stream, message):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f'live_chat_{stream.id}',
            {
                'type': 'chat.message',
                'event': 'message_created',
                'message': LiveChatMessageSerializer(message).data,
            },
        )
    except Exception:  # pragma: no cover - delivery depends on channel layer availability
        logger.exception('Failed to broadcast live gift message.', extra={'stream_id': stream.id, 'message_id': message.id})


class LiveGiftSendAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        stream = get_object_or_404(LiveStream.objects.select_related('owner'), pk=pk)
        if stream.status in {LiveStream.STATUS_ENDED, LiveStream.STATUS_FAILED}:
            return Response({'detail': 'Live stream has ended.'}, status=status.HTTP_400_BAD_REQUEST)

        if 'amount' in request.data:
            return self._send_amount_gift(request, stream)
        return self._send_fixed_gift(request, stream)

    def _send_amount_gift(self, request, stream):
        serializer = ContentGiftSendSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        amount = serializer.validated_data['amount']
        payment_method = serializer.validated_data['payment_method']

        try:
            tx, sender_balance, receiver_balance = GiftService.send_content_gift(
                sender=request.user,
                receiver=stream.owner,
                target_type=GiftTransaction.TARGET_LIVE_STREAM,
                target_id=stream.id,
                stream=stream,
                amount=amount,
                payment_method=payment_method,
            )
        except DjangoValidationError as exc:
            if _is_insufficient_balance(exc):
                return _insufficient_balance_response(payment_method)
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = {
            'amount': amount,
            'payment_method': payment_method,
            'sender': {'id': request.user.id, 'name': request.user.display_name},
        }
        room, _ = LiveChatRoom.objects.get_or_create(stream=stream)
        message = LiveChatMessage.objects.create(
            room=room,
            user=request.user,
            message_type=LiveChatMessage.TYPE_GIFT,
            type=LiveChatMessage.EVENT_GIFT,
            content=f'{request.user.display_name} sent {amount} {payment_method}',
            payload=payload,
        )
        _broadcast_live_gift_message(stream, message)
        return Response(
            {
                'ok': True,
                'event': {
                    'id': message.id,
                    'type': message.type,
                    'message': message.content,
                    'payload': message.payload,
                },
                'transaction': GiftTransactionSerializer(tx).data,
                'sender_balance': int(sender_balance),
                'receiver_balance': int(receiver_balance),
            },
            status=status.HTTP_201_CREATED,
        )

    def _send_fixed_gift(self, request, stream):
        serializer = GiftSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = serializer.validated_data

        if validated_data.get('gift_id'):
            gift = get_object_or_404(Gift, pk=validated_data['gift_id'])
        else:
            gift = get_object_or_404(Gift, code=validated_data['gift_code'])
        quantity = validated_data['quantity']
        cutoff = timezone.now() - timedelta(seconds=2)
        existing_tx = (
            GiftTransaction.objects.filter(
                sender=request.user,
                stream=stream,
                gift=gift,
                quantity=quantity,
                created_at__gte=cutoff,
            )
            .order_by('-created_at', '-id')
            .first()
        )
        if existing_tx is not None:
            response_serializer = GiftTransactionSerializer(existing_tx)
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        try:
            tx = GiftService.send_gift(
                sender=request.user,
                receiver=stream.owner,
                stream=stream,
                gift=gift,
                quantity=quantity,
            )
        except DjangoValidationError as exc:
            error_text = str(exc)
            if _is_insufficient_balance(exc):
                return _insufficient_balance_response(GiftTransaction.PAYMENT_MEOW_POINTS)
            if 'Gift is not active.' in error_text:
                return Response({'detail': 'Gift is not active.'}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'detail': error_text}, status=status.HTTP_400_BAD_REQUEST)

        total_cost = gift.points_price * quantity
        payload = {
            'gift_id': gift.id,
            'gift_code': gift.code,
            'gift_name': gift.name,
            'quantity': quantity,
            'coin_cost': gift.points_price,
            'total_cost': total_cost,
            'payment_method': GiftTransaction.PAYMENT_MEOW_POINTS,
            'sender': {'id': request.user.id, 'name': request.user.display_name},
        }
        room, _ = LiveChatRoom.objects.get_or_create(stream=stream)
        message = LiveChatMessage.objects.create(
            room=room,
            user=request.user,
            message_type=LiveChatMessage.TYPE_GIFT,
            type=LiveChatMessage.EVENT_GIFT,
            content=f'{request.user.display_name} sent {gift.name} x{quantity}',
            payload=payload,
        )
        _broadcast_live_gift_message(stream, message)
        response_serializer = GiftTransactionSerializer(tx)
        return Response(
            {
                'ok': True,
                'event': {
                    'id': message.id,
                    'type': message.type,
                    'message': message.content,
                    'payload': message.payload,
                },
                'transaction': response_serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )
