from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.db import IntegrityError
from django.db.models import Count, Exists, F, OuterRef, Q
from datetime import timedelta
import logging
from asgiref.sync import async_to_sync
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.models import (
    Category,
    ChannelSubscription,
    CommentLike,
    LiveChatMessage,
    LiveChatRoom,
    LiveStream,
    LiveStreamProduct,
    Product,
    SellerStore,
    Video,
    VideoComment,
    VideoLike,
    VideoView,
    generate_stream_key,
)
from apps.accounts.permissions import IsCreator, IsStaffOrSuperuser
from apps.accounts.serializers import (
    AccountPreferencesSerializer,
    AccountProfileSerializer,
    AdminUserSerializer,
    AdminVideoSerializer,
    LiveStreamSerializer,
    LiveStreamProductListingSerializer,
    LiveStreamProductManageCreateSerializer,
    LiveStreamProductManageUpdateSerializer,
    LiveChatMessageCreateSerializer,
    LiveChatMessageSerializer,
    EmailTokenObtainPairSerializer,
    PublicCategorySerializer,
    ProductSerializer,
    RegisterSerializer,
    SellerStoreSerializer,
    UserSerializer,
    VideoCommentCreateSerializer,
    VideoCommentSerializer,
    VideoInteractionSummarySerializer,
    VideoMetadataSerializer,
    VideoSerializer,
)
from apps.accounts.services import AntMediaLiveAdapter, generate_video_thumbnail

User = get_user_model()
logger = logging.getLogger(__name__)
try:
    from channels.layers import get_channel_layer
except ModuleNotFoundError:  # pragma: no cover
    def get_channel_layer():
        return None
LEGACY_CATEGORY_SLUG_ALIASES = {
    'tech': 'technology',
}


def annotate_videos_for_request(queryset, request):
    queryset = queryset.select_related('owner', 'category').annotate(
        view_count=Count('views', distinct=True),
    )
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        queryset = queryset.annotate(
            is_liked_value=Exists(
                VideoLike.objects.filter(video_id=OuterRef('pk'), user=user)
            ),
            is_subscribed_value=Exists(
                ChannelSubscription.objects.filter(channel_id=OuterRef('owner_id'), subscriber=user)
            ),
        )
    return queryset


def annotate_comments(queryset, request):
    queryset = queryset.select_related('user').annotate()
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        queryset = queryset.annotate(
            viewer_has_liked_value=Exists(
                CommentLike.objects.filter(comment_id=OuterRef('pk'), user=user)
            )
        )
    return queryset


class VideoPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class CommentPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class RegisterAPIView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class LoginAPIView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]


class RefreshAPIView(TokenRefreshView):
    permission_classes = [permissions.AllowAny]


class MeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response(serializer.data)


class AccountProfileAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        serializer = AccountProfileSerializer(request.user, context={'request': request})
        return Response(serializer.data)

    def patch(self, request):
        serializer = AccountProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class AccountPreferencesAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def get(self, request):
        serializer = AccountPreferencesSerializer(request.user)
        return Response(serializer.data)

    def patch(self, request):
        serializer = AccountPreferencesSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminUserListAPIView(generics.ListAPIView):
    queryset = User.objects.order_by('id')
    serializer_class = AdminUserSerializer
    permission_classes = [IsStaffOrSuperuser]


class AdminUserDetailAPIView(generics.RetrieveUpdateAPIView):
    queryset = User.objects.order_by('id')
    serializer_class = AdminUserSerializer
    permission_classes = [IsStaffOrSuperuser]


class AdminUserActivationAPIView(APIView):
    permission_classes = [IsStaffOrSuperuser]
    active = True

    def post(self, request, pk):
        user = generics.get_object_or_404(User, pk=pk)
        user.is_active = self.active
        user.save(update_fields=['is_active'])
        serializer = AdminUserSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)



class AdminVideoListAPIView(generics.ListAPIView):
    serializer_class = AdminVideoSerializer
    permission_classes = [IsStaffOrSuperuser]
    pagination_class = VideoPagination

    def get_queryset(self):
        queryset = annotate_videos_for_request(Video.objects.all(), self.request)
        search = self.request.query_params.get('search')
        owner = self.request.query_params.get('owner')
        category = self.request.query_params.get('category')
        status_filter = self.request.query_params.get('status')
        visibility = self.request.query_params.get('visibility')
        ordering = self.request.query_params.get('ordering')

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(description__icontains=search)
                | Q(owner__email__icontains=search)
                | Q(owner__first_name__icontains=search)
                | Q(owner__last_name__icontains=search)
            )

        if owner:
            if owner.isdigit():
                queryset = queryset.filter(owner_id=int(owner))
            else:
                queryset = queryset.filter(owner__email__icontains=owner)

        category = LEGACY_CATEGORY_SLUG_ALIASES.get(category, category)
        if category:
            queryset = queryset.filter(category__slug=category)

        if status_filter in {choice for choice, _ in Video.STATUS_CHOICES}:
            queryset = queryset.filter(status=status_filter)

        if visibility in {choice for choice, _ in Video.VISIBILITY_CHOICES}:
            queryset = queryset.filter(visibility=visibility)

        if ordering in {'created_at', '-created_at', 'updated_at', '-updated_at', 'like_count', '-like_count', 'comment_count', '-comment_count'}:
            queryset = queryset.order_by(ordering, '-id') if ordering.lstrip('-') in {'like_count', 'comment_count'} else queryset.order_by(ordering)
        else:
            queryset = queryset.order_by('-created_at', '-id')
        return queryset


class AdminVideoDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsStaffOrSuperuser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        return AdminVideoSerializer

    def get_queryset(self):
        return annotate_videos_for_request(Video.objects.all(), self.request)


class SellerStoreMeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get(self, request):
        store = SellerStore.objects.filter(owner=request.user).select_related('owner').first()
        if store is None:
            return Response({'detail': 'Store not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = SellerStoreSerializer(store, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        if SellerStore.objects.filter(owner=request.user).exists():
            return Response({'detail': 'Store already exists.'}, status=status.HTTP_409_CONFLICT)
        serializer = SellerStoreSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        store = serializer.save(owner=request.user)
        response_serializer = SellerStoreSerializer(store, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def patch(self, request):
        store = SellerStore.objects.filter(owner=request.user).select_related('owner').first()
        if store is None:
            return Response({'detail': 'Store not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = SellerStoreSerializer(store, data=request.data, partial=True, context={'request': request})
        serializer.is_valid(raise_exception=True)
        store = serializer.save()
        response_serializer = SellerStoreSerializer(store, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class SellerStoreMeProductListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    pagination_class = None

    def _store(self):
        return SellerStore.objects.filter(owner=self.request.user).first()

    def get_queryset(self):
        store = self._store()
        if store is None:
            return Product.objects.none()
        return Product.objects.filter(store=store).order_by('-created_at', '-id')

    def list(self, request, *args, **kwargs):
        if self._store() is None:
            return Response({'detail': 'Store not found.'}, status=status.HTTP_404_NOT_FOUND)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        store = self._store()
        if store is None:
            return Response({'detail': 'Store not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(store=store)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class SellerStoreMeProductDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_queryset(self):
        return Product.objects.filter(store__owner=self.request.user).select_related('store')


class PublicSellerStoreDetailAPIView(generics.RetrieveAPIView):
    serializer_class = SellerStoreSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'slug'

    def get_queryset(self):
        queryset = SellerStore.objects.select_related('owner')
        user = getattr(self.request, 'user', None)
        if user and user.is_authenticated:
            return queryset.filter(Q(is_active=True) | Q(owner=user)).distinct()
        return queryset.filter(is_active=True)


class PublicSellerStoreProductListAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, slug):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            store = SellerStore.objects.filter(slug=slug).filter(Q(is_active=True) | Q(owner=user)).first()
        else:
            store = SellerStore.objects.filter(slug=slug, is_active=True).first()
        if store is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        products = Product.objects.filter(store=store).order_by('-created_at', '-id')
        if not (user and user.is_authenticated and store.owner_id == user.id):
            products = products.filter(status=Product.STATUS_ACTIVE)

        serializer = ProductSerializer(products, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class LiveStreamProductManageListCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def _stream(self, request, pk):
        return generics.get_object_or_404(
            LiveStream.objects.select_related('owner'),
            pk=pk,
            owner=request.user,
        )

    def get(self, request, pk):
        stream = self._stream(request, pk)
        queryset = LiveStreamProduct.objects.filter(stream=stream).select_related('product', 'product__store')
        serializer = LiveStreamProductListingSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, pk):
        stream = self._stream(request, pk)
        serializer = LiveStreamProductManageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = generics.get_object_or_404(
            Product.objects.select_related('store'),
            pk=serializer.validated_data['product_id'],
            store__owner=request.user,
        )

        try:
            binding = LiveStreamProduct.objects.create(
                stream=stream,
                product=product,
                sort_order=serializer.validated_data.get('sort_order', 0),
                is_pinned=serializer.validated_data.get('is_pinned', False),
                is_active=serializer.validated_data.get('is_active', True),
                start_at=serializer.validated_data.get('start_at'),
                end_at=serializer.validated_data.get('end_at'),
            )
        except IntegrityError:
            return Response(
                {'detail': 'Active product binding already exists for this stream.'},
                status=status.HTTP_409_CONFLICT,
            )
        response_serializer = LiveStreamProductListingSerializer(binding, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class LiveStreamProductManageDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def _binding(self, request, pk, binding_id):
        return generics.get_object_or_404(
            LiveStreamProduct.objects.select_related('stream', 'product', 'product__store'),
            pk=binding_id,
            stream_id=pk,
            stream__owner=request.user,
        )

    def patch(self, request, pk, binding_id):
        binding = self._binding(request, pk, binding_id)
        serializer = LiveStreamProductManageUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(binding, field, value)
        binding.save(update_fields=list(serializer.validated_data.keys()))
        response_serializer = LiveStreamProductListingSerializer(binding, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, binding_id):
        binding = self._binding(request, pk, binding_id)
        binding.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LiveStreamProductPublicListAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        stream = generics.get_object_or_404(
            LiveStream.objects.select_related('owner'),
            pk=pk,
        )
        if stream.visibility == LiveStream.VISIBILITY_PRIVATE:
            user = getattr(request, 'user', None)
            if not (user and user.is_authenticated and user.id == stream.owner_id):
                return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        queryset = (
            LiveStreamProduct.objects.filter(
                stream=stream,
                is_active=True,
                product__status=Product.STATUS_ACTIVE,
                product__store__is_active=True,
            )
            .select_related('product', 'product__store')
            .order_by('-is_pinned', 'sort_order', '-created_at', '-id')
        )
        serializer = LiveStreamProductListingSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class LiveChatMessageListCreateAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def _stream_for_read(self, request, pk):
        stream = generics.get_object_or_404(LiveStream.objects.select_related('owner'), pk=pk)
        if stream.visibility == LiveStream.VISIBILITY_PRIVATE:
            user = getattr(request, 'user', None)
            if not (user and user.is_authenticated and user.id == stream.owner_id):
                return None
        return stream

    def _stream_for_write(self, request, pk):
        stream = self._stream_for_read(request, pk)
        user = getattr(request, 'user', None)
        if stream is None or not (user and user.is_authenticated):
            return None
        if stream.visibility != LiveStream.VISIBILITY_PUBLIC and user.id != stream.owner_id:
            return None
        return stream

    def _room(self, stream):
        room, _ = LiveChatRoom.objects.get_or_create(stream=stream)
        return room

    def get(self, request, pk):
        stream = self._stream_for_read(request, pk)
        if stream is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        room = self._room(stream)
        if not room.is_enabled:
            return Response({'results': [], 'next_after_id': None}, status=status.HTTP_200_OK)

        after_id = request.query_params.get('after_id')
        try:
            limit = int(request.query_params.get('limit', 50) or 50)
        except (TypeError, ValueError):
            limit = 50
        if limit <= 0:
            limit = 50
        limit = min(limit, 100)
        queryset = LiveChatMessage.objects.filter(room=room, is_deleted=False).select_related('user', 'product', 'product__store')
        if after_id and str(after_id).isdigit():
            queryset = queryset.filter(id__gt=int(after_id))
        messages = list(queryset.order_by('id')[:limit])
        serializer = LiveChatMessageSerializer(messages, many=True, context={'request': request})
        next_after_id = messages[-1].id if messages else None
        return Response({'results': serializer.data, 'next_after_id': next_after_id}, status=status.HTTP_200_OK)

    def post(self, request, pk):
        stream = self._stream_for_write(request, pk)
        if stream is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        room = self._room(stream)
        if not room.is_enabled:
            return Response({'detail': 'Chat is disabled for this stream.'}, status=status.HTTP_409_CONFLICT)

        serializer = LiveChatMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = request.user
        if room.slow_mode_seconds > 0:
            cutoff = timezone.now() - timedelta(seconds=room.slow_mode_seconds)
            recent_exists = LiveChatMessage.objects.filter(room=room, user=user, created_at__gte=cutoff, is_deleted=False).exists()
            if recent_exists:
                return Response({'detail': 'Slow mode is enabled. Please wait before sending again.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        reply_to = None
        reply_to_id = serializer.validated_data.get('reply_to_id')
        if reply_to_id:
            reply_to = generics.get_object_or_404(LiveChatMessage, pk=reply_to_id, room=room)

        product = None
        product_id = serializer.validated_data.get('product_id')
        if serializer.validated_data.get('message_type') == LiveChatMessage.TYPE_PRODUCT:
            if not product_id:
                return Response({'product_id': ['This field is required for product messages.']}, status=status.HTTP_400_BAD_REQUEST)
            product = generics.get_object_or_404(Product.objects.select_related('store'), pk=product_id, status=Product.STATUS_ACTIVE)

        message = LiveChatMessage.objects.create(
            room=room,
            user=user,
            message_type=serializer.validated_data.get('message_type', LiveChatMessage.TYPE_TEXT),
            content=serializer.validated_data.get('content', ''),
            reply_to=reply_to,
            product=product,
        )
        response_serializer = LiveChatMessageSerializer(message, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class LiveChatMessageModerationAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _message(self, request, pk, message_id):
        message = generics.get_object_or_404(
            LiveChatMessage.objects.select_related('room__stream'),
            pk=message_id,
            room__stream_id=pk,
        )
        is_owner = message.room.stream.owner_id == request.user.id
        if not (is_owner or request.user.is_staff):
            return None
        return message

    def patch(self, request, pk, message_id):
        message = self._message(request, pk, message_id)
        if message is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        message.is_pinned = not message.is_pinned
        message.save(update_fields=['is_pinned'])
        serializer = LiveChatMessageSerializer(message, context={'request': request})
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            try:
                async_to_sync(channel_layer.group_send)(
                    f'live_chat_{pk}',
                    {
                        'type': 'chat.message',
                        'event': 'message_updated',
                        'message': serializer.data,
                    },
                )
            except Exception:  # pragma: no cover
                logger.debug('live chat ws broadcast failed for pin action', exc_info=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, message_id):
        message = self._message(request, pk, message_id)
        if message is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        deleted_id = message.id
        message.is_deleted = True
        message.content = ''
        message.save(update_fields=['is_deleted', 'content'])
        channel_layer = get_channel_layer()
        if channel_layer is not None:
            try:
                async_to_sync(channel_layer.group_send)(
                    f'live_chat_{pk}',
                    {
                        'type': 'chat.message',
                        'event': 'message_deleted',
                        'message': {'id': deleted_id},
                    },
                )
            except Exception:  # pragma: no cover
                logger.debug('live chat ws broadcast failed for delete action', exc_info=True)
        return Response(status=status.HTTP_204_NO_CONTENT)



class LiveStreamListAPIView(generics.ListAPIView):
    serializer_class = LiveStreamSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        queryset = LiveStream.objects.select_related('category', 'owner')
        user = getattr(self.request, 'user', None)
        if user and user.is_authenticated:
            return queryset.filter(
                Q(visibility=LiveStream.VISIBILITY_PUBLIC) | Q(owner=user)
            ).distinct()
        return queryset.filter(visibility=LiveStream.VISIBILITY_PUBLIC)


class LiveStreamCreateAPIView(generics.CreateAPIView):
    serializer_class = LiveStreamSerializer
    permission_classes = [permissions.IsAuthenticated, IsCreator]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class LiveStreamDetailAPIView(generics.RetrieveAPIView):
    serializer_class = LiveStreamSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = LiveStream.objects.select_related('category', 'owner')
        user = getattr(self.request, 'user', None)
        if user and user.is_authenticated:
            return queryset.filter(
                Q(visibility=LiveStream.VISIBILITY_PUBLIC) | Q(owner=user)
            ).distinct()
        return queryset.filter(visibility=LiveStream.VISIBILITY_PUBLIC)

    def retrieve(self, request, *args, **kwargs):
        stream = self.get_object()
        serializer = self.get_serializer(stream)
        payload = dict(serializer.data)
        payload['stream_key'] = stream.stream_key
        return Response(payload, status=status.HTTP_200_OK)


class LiveStreamStatusDetailAPIView(generics.RetrieveAPIView):
    serializer_class = LiveStreamSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = LiveStream.objects.select_related('category', 'owner')
        user = getattr(self.request, 'user', None)
        if user and user.is_authenticated:
            return queryset.filter(
                Q(visibility=LiveStream.VISIBILITY_PUBLIC) | Q(owner=user)
            ).distinct()
        return queryset.filter(visibility=LiveStream.VISIBILITY_PUBLIC)


class LiveStreamUpdateAPIView(generics.UpdateAPIView):
    serializer_class = LiveStreamSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    http_method_names = ['patch']

    def get_queryset(self):
        return LiveStream.objects.filter(owner=self.request.user).select_related('category', 'owner')


class LiveStreamStatusAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsCreator]
    new_status = LiveStream.STATUS_IDLE

    def post(self, request, pk):
        stream = generics.get_object_or_404(LiveStream.objects.select_related('category'), pk=pk, owner=request.user)
        now = timezone.now()

        if self.new_status == LiveStream.STATUS_LIVE:
            if stream.status != LiveStream.STATUS_IDLE:
                return Response(
                    {'detail': 'Only idle streams can be started.'},
                    status=status.HTTP_409_CONFLICT,
                )
            stream.status = LiveStream.STATUS_LIVE
            stream.started_at = now
            stream.ended_at = None
            stream.save(update_fields=['status', 'started_at', 'ended_at'])
        elif self.new_status == LiveStream.STATUS_ENDED:
            if stream.status != LiveStream.STATUS_LIVE:
                return Response(
                    {'detail': 'Only live streams can be ended.'},
                    status=status.HTTP_409_CONFLICT,
                )
            stream.status = LiveStream.STATUS_ENDED
            stream.ended_at = now
            stream.save(update_fields=['status', 'ended_at'])

        serializer = LiveStreamSerializer(stream, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class LiveStreamPrepareAPIView(APIView):
    """Prepare a live stream and return the backend-owned publish stream id.

    Contract: the frontend should publish to Ant Media using the stream id from
    this response (`stream_key` and `publish_session.ant_media.stream_id`).
    """
    permission_classes = [permissions.IsAuthenticated, IsCreator]

    def post(self, request, pk):
        stream = generics.get_object_or_404(
            LiveStream.objects.select_related('category'),
            pk=pk,
            owner=request.user,
        )
        if stream.status != LiveStream.STATUS_IDLE:
            return Response(
                {'detail': 'Only idle streams can be prepared.'},
                status=status.HTTP_409_CONFLICT,
            )
        stream.stream_key = generate_stream_key()
        stream.save(update_fields=['stream_key'])
        adapter = AntMediaLiveAdapter()
        ensure_result = adapter.ensure_broadcast(stream)
        if not ensure_result.get('ok'):
            return Response(
                {
                    'detail': ensure_result.get('message'),
                    'error': ensure_result.get('error'),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        ant_stream_id = ensure_result.get('stream_id') or stream.stream_key
        if ant_stream_id != stream.stream_key:
            stream.stream_key = ant_stream_id
            stream.save(update_fields=['stream_key'])
        logger.debug('live_prepare persisted stream_id live_id=%s stream_id=%s', stream.id, stream.stream_key)

        publish_config = adapter.get_browser_publish_config(stream)
        ant_media_config = publish_config.get('config', {})

        masked_stream_id = stream.stream_key[:6] + '...' if stream.stream_key else None
        logger.debug(
            'live_prepare generated publish session live_id=%s user_id=%s stream_id=%s websocket_url=%s adaptor_script_url=%s',
            stream.id,
            request.user.id,
            masked_stream_id,
            ant_media_config.get('websocket_url'),
            ant_media_config.get('adaptor_script_url'),
        )

        serializer = LiveStreamSerializer(stream, context={'request': request})
        payload = serializer.data
        logger.debug('live_prepare returning stream_id live_id=%s stream_id=%s', stream.id, stream.stream_key)
        return Response(
            {
                'id': stream.id,
                'rtmp_base': settings.ANT_MEDIA_RTMP_BASE or None,
                'stream_key': stream.stream_key,
                'playback_url': payload.get('playback_url'),
                'watch_url': payload.get('watch_url'),
                'status': payload.get('status'),
                'message': 'Live stream prepared.',
                'publish_session': {
                    'mode': 'browser',
                    'ant_media': {
                        'websocket_url': ant_media_config.get('websocket_url'),
                        'adaptor_script_url': ant_media_config.get('adaptor_script_url'),
                        # Keep this tied to persisted backend state to avoid any
                        # ambiguity about publish stream-id ownership.
                        'stream_id': stream.stream_key,
                    },
                },
            },
            status=status.HTTP_200_OK,
        )


class VideoListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = VideoPagination

    def get_queryset(self):
        queryset = Video.objects.filter(owner=self.request.user)
        queryset = annotate_videos_for_request(queryset, self.request)
        return self.filter_videos(queryset)

    def perform_create(self, serializer):
        video = serializer.save(owner=self.request.user)
        if generate_video_thumbnail(video):
            video.save(update_fields=['thumbnail'])

    def filter_videos(self, queryset):
        category = self.request.query_params.get('category')
        search = self.request.query_params.get('search')
        ordering = self.request.query_params.get('ordering')

        category = LEGACY_CATEGORY_SLUG_ALIASES.get(category, category)
        if category:
            queryset = queryset.filter(category__slug=category)
        if search:
            queryset = queryset.filter(Q(title__icontains=search))
        if ordering in {'created_at', '-created_at'}:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by('-created_at', '-id')
        return queryset


class VideoDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        if self.request.method in {'PATCH', 'PUT'}:
            return VideoMetadataSerializer
        return VideoSerializer

    def get_queryset(self):
        queryset = Video.objects.filter(owner=self.request.user)
        return annotate_videos_for_request(queryset, self.request)


class VideoRegenerateThumbnailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [FormParser, JSONParser, MultiPartParser]

    def post(self, request, pk):
        video = generics.get_object_or_404(Video, pk=pk, owner=request.user)
        time_offset = request.data.get('time_offset', 1)

        try:
            time_offset = float(time_offset)
        except (TypeError, ValueError):
            return Response(
                {'detail': 'time_offset must be a number.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        generate_video_thumbnail(video, time_offset=time_offset)
        video.save(update_fields=['thumbnail'])
        video = annotate_videos_for_request(Video.objects.filter(pk=video.pk), request).get()
        serializer = VideoSerializer(video, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class PublicVideoListAPIView(generics.ListAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = VideoPagination

    def get_queryset(self):
        queryset = annotate_videos_for_request(
            Video.objects.filter(visibility=Video.VISIBILITY_PUBLIC),
            self.request,
        )
        category = self.request.query_params.get('category')
        search = self.request.query_params.get('search')
        ordering = self.request.query_params.get('ordering')

        category = LEGACY_CATEGORY_SLUG_ALIASES.get(category, category)
        if category:
            queryset = queryset.filter(category__slug=category)
        if search:
            queryset = queryset.filter(Q(title__icontains=search))
        if ordering in {'created_at', '-created_at'}:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by('-created_at', '-id')
        return queryset


class PublicVideoDetailAPIView(generics.RetrieveAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        return annotate_videos_for_request(
            Video.objects.filter(visibility=Video.VISIBILITY_PUBLIC),
            self.request,
        )


class PublicRelatedVideoListAPIView(generics.ListAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        current_video = generics.get_object_or_404(
            Video.objects.select_related('category').filter(visibility=Video.VISIBILITY_PUBLIC),
            pk=self.kwargs['pk'],
        )
        limit = self.request.query_params.get('limit', 8)

        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 8

        queryset = annotate_videos_for_request(
            Video.objects.filter(visibility=Video.VISIBILITY_PUBLIC).exclude(pk=current_video.pk),
            self.request,
        )
        if current_video.category_id:
            queryset = queryset.filter(category=current_video.category_id)
        return queryset.order_by('-created_at', '-id')[:limit]


class PublicVideoInteractionSummaryAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        video = generics.get_object_or_404(
            annotate_videos_for_request(
                Video.objects.filter(visibility=Video.VISIBILITY_PUBLIC),
                request,
            ),
            pk=pk,
        )
        serializer = VideoInteractionSummarySerializer(video, context={'request': request})
        return Response(serializer.data)


class VideoLikeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        video = generics.get_object_or_404(Video.objects.select_related('owner'), pk=pk)
        _, created = VideoLike.objects.get_or_create(video=video, user=request.user)
        if created:
            Video.objects.filter(pk=video.pk).update(like_count=F('like_count') + 1)
        video.refresh_from_db(fields=['like_count', 'comment_count'])
        video = annotate_videos_for_request(Video.objects.filter(pk=video.pk), request).get()
        serializer = VideoInteractionSummarySerializer(video, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        video = generics.get_object_or_404(Video.objects.select_related('owner'), pk=pk)
        deleted_count, _ = VideoLike.objects.filter(video=video, user=request.user).delete()
        if deleted_count:
            Video.objects.filter(pk=video.pk, like_count__gt=0).update(like_count=F('like_count') - 1)
        video.refresh_from_db(fields=['like_count', 'comment_count'])
        video = annotate_videos_for_request(Video.objects.filter(pk=video.pk), request).get()
        serializer = VideoInteractionSummarySerializer(video, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class ChannelSubscriptionAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        channel = generics.get_object_or_404(User, pk=pk)
        if channel.pk == request.user.pk:
            return Response({'detail': 'You cannot subscribe to your own channel.'}, status=status.HTTP_400_BAD_REQUEST)

        _, created = ChannelSubscription.objects.get_or_create(channel=channel, subscriber=request.user)
        if created:
            User.objects.filter(pk=channel.pk).update(subscriber_count=F('subscriber_count') + 1)
        channel.refresh_from_db(fields=['subscriber_count'])
        return Response(
            {
                'channel_id': channel.pk,
                'subscriber_count': channel.subscriber_count,
                'viewer_is_subscribed': True,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        channel = generics.get_object_or_404(User, pk=pk)
        deleted_count, _ = ChannelSubscription.objects.filter(channel=channel, subscriber=request.user).delete()
        if deleted_count:
            User.objects.filter(pk=channel.pk, subscriber_count__gt=0).update(subscriber_count=F('subscriber_count') - 1)
        channel.refresh_from_db(fields=['subscriber_count'])
        return Response(
            {
                'channel_id': channel.pk,
                'subscriber_count': channel.subscriber_count,
                'viewer_is_subscribed': False,
            },
            status=status.HTTP_200_OK,
        )


class PublicVideoCommentListAPIView(generics.ListAPIView):
    serializer_class = VideoCommentSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = CommentPagination

    def get_queryset(self):
        video = generics.get_object_or_404(
            Video,
            pk=self.kwargs['pk'],
            visibility=Video.VISIBILITY_PUBLIC,
        )
        parent_id = self.request.query_params.get('parent_id')
        queryset = VideoComment.objects.filter(video=video, is_deleted=False)

        if parent_id is None:
            queryset = queryset.filter(parent__isnull=True)
        else:
            queryset = queryset.filter(parent_id=parent_id)

        queryset = annotate_comments(queryset, self.request)
        return queryset.order_by('-created_at', '-id')


class VideoCommentCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def post(self, request, pk):
        video = generics.get_object_or_404(Video.objects.select_related('owner'), pk=pk)
        serializer = VideoCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        parent = None
        parent_id = serializer.validated_data.get('parent_id')
        if parent_id is not None:
            parent = generics.get_object_or_404(VideoComment, pk=parent_id)
            if parent.video_id != video.pk:
                return Response(
                    {'parent_id': ['parent comment must belong to the same video.']},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        comment = VideoComment.objects.create(
            video=video,
            user=request.user,
            parent=parent,
            content=serializer.validated_data['content'],
        )
        Video.objects.filter(pk=video.pk).update(comment_count=F('comment_count') + 1)
        if parent is not None:
            VideoComment.objects.filter(pk=parent.pk).update(reply_count=F('reply_count') + 1)

        comment = annotate_comments(VideoComment.objects.filter(pk=comment.pk), request).get()
        response_serializer = VideoCommentSerializer(comment, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class PublicVideoViewTrackAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, pk):
        video = generics.get_object_or_404(
            Video,
            pk=pk,
            visibility=Video.VISIBILITY_PUBLIC,
        )
        viewer = request.user if request.user.is_authenticated else None
        VideoView.objects.create(video=video, viewer=viewer)
        video = annotate_videos_for_request(Video.objects.filter(pk=video.pk), request).get()
        serializer = VideoSerializer(video, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class PublicCategoryListAPIView(generics.ListAPIView):
    serializer_class = PublicCategorySerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        return Category.objects.filter(is_active=True).exclude(
            slug__in=LEGACY_CATEGORY_SLUG_ALIASES.keys()
        ).order_by('sort_order', 'name')
