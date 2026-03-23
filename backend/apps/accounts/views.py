from django.contrib.auth import get_user_model
from django.db.models import Count, Exists, OuterRef, Q
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.models import Category, Video, VideoLike, VideoView
from apps.accounts.permissions import IsStaffOrSuperuser
from apps.accounts.services import generate_video_thumbnail
from apps.accounts.serializers import (
    AdminUserSerializer,
    EmailTokenObtainPairSerializer,
    PublicCategorySerializer,
    RegisterSerializer,
    UserSerializer,
    VideoMetadataSerializer,
    VideoSerializer,
)

User = get_user_model()
LEGACY_CATEGORY_SLUG_ALIASES = {
    'tech': 'technology',
}


def annotate_videos_for_request(queryset, request):
    queryset = queryset.annotate(
        like_count=Count('likes', distinct=True),
        view_count=Count('views', distinct=True),
    )
    user = getattr(request, 'user', None)
    if user and user.is_authenticated:
        queryset = queryset.annotate(
            is_liked_value=Exists(
                VideoLike.objects.filter(video_id=OuterRef('pk'), user=user)
            )
        )
    return queryset


class VideoPagination(PageNumberPagination):
    page_size = 10
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


class VideoListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = VideoPagination

    def get_queryset(self):
        queryset = Video.objects.filter(owner=self.request.user).select_related('category')
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
        queryset = Video.objects.filter(owner=self.request.user).select_related('category')
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
        serializer = VideoSerializer(video, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class PublicVideoListAPIView(generics.ListAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = VideoPagination

    def get_queryset(self):
        queryset = Video.objects.select_related('category').all()
        queryset = annotate_videos_for_request(queryset, self.request)
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
        queryset = Video.objects.select_related('category').all()
        return annotate_videos_for_request(queryset, self.request)


class PublicRelatedVideoListAPIView(generics.ListAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        current_video = generics.get_object_or_404(
            Video.objects.select_related('category'),
            pk=self.kwargs['pk'],
        )
        limit = self.request.query_params.get('limit', 8)

        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 8

        queryset = Video.objects.select_related('category').exclude(pk=current_video.pk)
        queryset = annotate_videos_for_request(queryset, self.request)
        if current_video.category_id:
            queryset = queryset.filter(category=current_video.category_id)
        return queryset.order_by('-created_at', '-id')[:limit]


class VideoLikeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        video = generics.get_object_or_404(Video.objects.select_related('category'), pk=pk)
        VideoLike.objects.get_or_create(video=video, user=request.user)
        video = annotate_videos_for_request(Video.objects.select_related('category').filter(pk=video.pk), request).get()
        serializer = VideoSerializer(video, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class VideoUnlikeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        video = generics.get_object_or_404(Video.objects.select_related('category'), pk=pk)
        VideoLike.objects.filter(video=video, user=request.user).delete()
        video = annotate_videos_for_request(Video.objects.select_related('category').filter(pk=video.pk), request).get()
        serializer = VideoSerializer(video, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class PublicVideoViewTrackAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, pk):
        video = generics.get_object_or_404(Video.objects.select_related('category'), pk=pk)
        viewer = request.user if request.user.is_authenticated else None
        VideoView.objects.create(video=video, viewer=viewer)
        video = annotate_videos_for_request(Video.objects.select_related('category').filter(pk=video.pk), request).get()
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
