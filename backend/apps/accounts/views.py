from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.db.models import Count, Exists, F, OuterRef, Q
import logging
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
    LiveStream,
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
    EmailTokenObtainPairSerializer,
    PublicCategorySerializer,
    RegisterSerializer,
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
        return Response(
            {
                'id': stream.id,
                'rtmp_base': settings.ANT_MEDIA_RTMP_BASE or None,
                'stream_key': stream.stream_key,
                'playback_url': payload.get('playback_url'),
                'watch_url': payload.get('watch_url'),
                'status': payload.get('status'),
                'message': 'Live stream prepared.',
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
