from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.models import Video
from apps.accounts.permissions import IsStaffOrSuperuser
from apps.accounts.serializers import (
    AdminUserSerializer,
    EmailTokenObtainPairSerializer,
    RegisterSerializer,
    UserSerializer,
    VideoSerializer,
)

User = get_user_model()


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
    parser_classes = [MultiPartParser, FormParser]
    pagination_class = VideoPagination

    def get_queryset(self):
        queryset = Video.objects.filter(owner=self.request.user)
        return self.filter_videos(queryset)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def filter_videos(self, queryset):
        category = self.request.query_params.get('category')
        search = self.request.query_params.get('search')
        ordering = self.request.query_params.get('ordering')

        if category:
            queryset = queryset.filter(category=category)
        if search:
            queryset = queryset.filter(Q(title__icontains=search))
        if ordering in {'created_at', '-created_at'}:
            queryset = queryset.order_by(ordering)
        return queryset


class VideoDetailAPIView(generics.RetrieveDestroyAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Video.objects.filter(owner=self.request.user)


class PublicVideoListAPIView(generics.ListAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = VideoPagination

    def get_queryset(self):
        queryset = Video.objects.all()
        category = self.request.query_params.get('category')
        search = self.request.query_params.get('search')
        ordering = self.request.query_params.get('ordering')

        if category:
            queryset = queryset.filter(category=category)
        if search:
            queryset = queryset.filter(Q(title__icontains=search))
        if ordering in {'created_at', '-created_at'}:
            queryset = queryset.order_by(ordering)
        return queryset


class PublicVideoDetailAPIView(generics.RetrieveAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]
    queryset = Video.objects.all()
