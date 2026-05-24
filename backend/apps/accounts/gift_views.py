from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta
from rest_framework import generics, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.gift_serializers import GiftSendSerializer, GiftSerializer, GiftTransactionSerializer
from apps.accounts.models import Gift, GiftTransaction, LiveStream, LiveChatMessage, LiveChatRoom
from apps.accounts.services import GiftService


class GiftListAPIView(generics.ListAPIView):
    permission_classes = [AllowAny]
    serializer_class = GiftSerializer
    pagination_class = None

    def get_queryset(self):
        return Gift.objects.filter(is_active=True).order_by('sort_order', 'id')


class LiveGiftSendAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        stream = get_object_or_404(LiveStream.objects.select_related('owner'), pk=pk)
        if stream.status in {LiveStream.STATUS_ENDED, LiveStream.STATUS_FAILED}:
            return Response({'detail': 'Live stream has ended.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = GiftSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client_request_id = (request.data.get('client_request_id') or '').strip()

        gift = get_object_or_404(Gift, code=serializer.validated_data['gift_code'])
        cutoff = timezone.now() - timedelta(seconds=2)
        existing_tx = (
            GiftTransaction.objects.filter(
                sender=request.user,
                stream=stream,
                gift=gift,
                quantity=serializer.validated_data['quantity'],
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
                quantity=serializer.validated_data['quantity'],
            )
        except DjangoValidationError as exc:
            error_text = str(exc)
            if 'Insufficient Meow Points balance.' in error_text:
                return Response(
                    {'code': 'insufficient_balance', 'detail': 'Insufficient Meow Points balance.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if 'Gift is not active.' in error_text:
                return Response({'detail': 'Gift is not active.'}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'detail': error_text}, status=status.HTTP_400_BAD_REQUEST)

        room, _ = LiveChatRoom.objects.get_or_create(stream=stream)
        message = LiveChatMessage.objects.create(
            room=room,
            user=request.user,
            message_type=LiveChatMessage.TYPE_GIFT,
            type=LiveChatMessage.EVENT_GIFT,
            content=f'{request.user.display_name} sent {gift.name} x{serializer.validated_data["quantity"]}',
            payload={
                'gift_id': gift.id,
                'gift_name': gift.name,
                'quantity': serializer.validated_data['quantity'],
                'sender': {'id': request.user.id, 'name': request.user.display_name},
            },
        )
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
