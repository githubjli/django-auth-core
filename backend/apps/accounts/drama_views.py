from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.drama_serializers import (
    AccountDramaFavoriteItemSerializer,
    AccountDramaProgressItemSerializer,
    DramaEpisodeSerializer,
    DramaFavoriteStateSerializer,
    DramaProgressSaveSerializer,
    DramaSeriesSerializer,
    DramaWatchProgressSerializer,
)
from apps.accounts.models import DramaEpisode, DramaFavorite, DramaSeries, DramaWatchProgress


class DramaSeriesPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class DramaSeriesListAPIView(generics.ListAPIView):
    serializer_class = DramaSeriesSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        queryset = (
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED)
            .annotate(
                free_episode_count=Count('episodes', filter=Q(episodes__is_active=True, episodes__is_free=True)),
                locked_episode_count=Count('episodes', filter=Q(episodes__is_active=True, episodes__is_free=False)),
            )
            .order_by('-created_at', '-id')
        )

        category = self.request.query_params.get('category')
        if category:
            if category.isdigit():
                queryset = queryset.filter(category_id=int(category))
            else:
                queryset = queryset.filter(category__slug=category)

        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        if not user.is_authenticated:
            return context
        series_ids = [series.id for series in self.get_queryset()]
        context['favorite_series_ids'] = set(
            DramaFavorite.objects.filter(user=user, series_id__in=series_ids).values_list('series_id', flat=True)
        )
        progress_items = DramaWatchProgress.objects.filter(user=user, series_id__in=series_ids).select_related('episode')
        context['progress_by_series_id'] = {item.series_id: item for item in progress_items}
        return context


class DramaSeriesDetailAPIView(generics.RetrieveAPIView):
    serializer_class = DramaSeriesSerializer

    def get_queryset(self):
        return DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED).annotate(
            free_episode_count=Count('episodes', filter=Q(episodes__is_active=True, episodes__is_free=True)),
            locked_episode_count=Count('episodes', filter=Q(episodes__is_active=True, episodes__is_free=False)),
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        user = self.request.user
        if not user.is_authenticated:
            return context
        series_id = self.kwargs['pk']
        context['favorite_series_ids'] = set(
            DramaFavorite.objects.filter(user=user, series_id=series_id).values_list('series_id', flat=True)
        )
        progress_items = DramaWatchProgress.objects.filter(user=user, series_id=series_id).select_related('episode')
        context['progress_by_series_id'] = {item.series_id: item for item in progress_items}
        return context


class DramaEpisodeListAPIView(APIView):
    def get(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        episodes = DramaEpisode.objects.filter(series=series, is_active=True).order_by('sort_order', 'episode_no', 'id')
        serializer = DramaEpisodeSerializer(episodes, many=True, context={'request': request})
        return Response({'series_id': series.id, 'episodes': serializer.data})


class DramaEpisodeDetailAPIView(APIView):
    def get(self, request, pk, episode_no):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        episode = get_object_or_404(
            DramaEpisode.objects.filter(series=series, is_active=True),
            episode_no=episode_no,
        )
        serializer = DramaEpisodeSerializer(episode, context={'request': request})
        return Response(serializer.data)


class DramaProgressUpsertAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        serializer = DramaProgressSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        episode = get_object_or_404(
            DramaEpisode.objects.filter(series=series, is_active=True),
            pk=serializer.validated_data['episode_id'],
        )
        progress, _created = DramaWatchProgress.objects.update_or_create(
            user=request.user,
            series=series,
            defaults={
                'episode': episode,
                'progress_seconds': serializer.validated_data['progress_seconds'],
                'completed': serializer.validated_data['completed'],
            },
        )
        response_serializer = DramaWatchProgressSerializer(progress)
        return Response(response_serializer.data)


class DramaFavoriteAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        with transaction.atomic():
            favorite, created = DramaFavorite.objects.get_or_create(user=request.user, series=series)
            if created:
                DramaSeries.objects.filter(pk=series.id).update(favorite_count=F('favorite_count') + 1)
        series.refresh_from_db(fields=['favorite_count'])
        serializer = DramaFavoriteStateSerializer(
            {'series_id': series.id, 'is_favorited': True, 'favorite_count': series.favorite_count}
        )
        return Response(serializer.data)

    def delete(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        with transaction.atomic():
            deleted, _ = DramaFavorite.objects.filter(user=request.user, series=series).delete()
            if deleted:
                DramaSeries.objects.filter(pk=series.id, favorite_count__gt=0).update(favorite_count=F('favorite_count') - 1)
        series.refresh_from_db(fields=['favorite_count'])
        serializer = DramaFavoriteStateSerializer(
            {'series_id': series.id, 'is_favorited': False, 'favorite_count': series.favorite_count}
        )
        return Response(serializer.data)


class AccountDramaProgressListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountDramaProgressItemSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        return (
            DramaWatchProgress.objects.filter(user=self.request.user, series__is_active=True, episode__is_active=True)
            .select_related('series', 'episode')
            .order_by('-updated_at', '-id')
        )


class AccountDramaFavoritesListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AccountDramaFavoriteItemSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        return (
            DramaFavorite.objects.filter(user=self.request.user, series__is_active=True, series__status=DramaSeries.STATUS_PUBLISHED)
            .select_related('series')
            .order_by('-created_at', '-id')
        )
