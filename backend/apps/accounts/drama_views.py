from django.db import transaction
from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from datetime import timedelta
from rest_framework import generics
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.permissions import BasePermission
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.gift_serializers import GiftSendSerializer, GiftTransactionSerializer
from apps.accounts.drama_serializers import (
    AccountDramaFavoriteItemSerializer,
    AccountDramaProgressItemSerializer,
    DramaCommentCreateSerializer,
    DramaCommentSerializer,
    DramaEpisodeSerializer,
    CreatorDramaEpisodeSerializer,
    CreatorDramaSeriesSerializer,
    DramaEpisodeUnlockRequestSerializer,
    DramaFavoriteStateSerializer,
    DramaInteractionSummarySerializer,
    DramaUnlockResponseSerializer,
    DramaProgressSaveSerializer,
    DramaSeriesSerializer,
    DramaWatchProgressSerializer,
)
from apps.accounts.models import ChannelSubscription, DramaComment, DramaEpisode, DramaFavorite, DramaSeries, DramaSeriesView, DramaShare, DramaUnlock, DramaWatchProgress, Gift, GiftTransaction
from apps.accounts.services import DramaAccessService, GiftService


def get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class DramaSeriesPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class DramaSeriesListAPIView(generics.ListAPIView):
    serializer_class = DramaSeriesSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        queryset = (
            DramaSeries.objects.select_related('owner').filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED)
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
        owner_ids = [owner_id for owner_id in self.get_queryset().values_list('owner_id', flat=True) if owner_id]
        context['subscribed_owner_ids'] = set(
            ChannelSubscription.objects.filter(subscriber=user, channel_id__in=owner_ids).values_list('channel_id', flat=True)
        )
        return context


class DramaSeriesDetailAPIView(generics.RetrieveAPIView):
    serializer_class = DramaSeriesSerializer

    def get_queryset(self):
        return DramaSeries.objects.select_related('owner').filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED).annotate(
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
        owner_id = DramaSeries.objects.filter(pk=series_id).values_list('owner_id', flat=True).first()
        context['subscribed_owner_ids'] = set(
            ChannelSubscription.objects.filter(subscriber=user, channel_id=owner_id).values_list('channel_id', flat=True)
        ) if owner_id else set()
        return context


class DramaEpisodeListAPIView(APIView):
    def get(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        episodes = DramaEpisode.objects.filter(series=series, is_active=True).order_by('sort_order', 'episode_no', 'id')
        unlocked_episode_ids: set[int] = set()
        has_active_membership = False
        if request.user.is_authenticated:
            unlocked_episode_ids = set(
                DramaUnlock.objects.filter(user=request.user, series=series).values_list('episode_id', flat=True)
            )
            has_active_membership = DramaAccessService.has_active_membership(request.user)
        serializer = DramaEpisodeSerializer(
            episodes,
            many=True,
            context={
                'request': request,
                'unlocked_episode_ids': unlocked_episode_ids,
                'has_active_membership': has_active_membership,
            },
        )
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
        unlocked_episode_ids: set[int] = set()
        has_active_membership = False
        if request.user.is_authenticated:
            unlocked_episode_ids = set(
                DramaUnlock.objects.filter(user=request.user, series=series).values_list('episode_id', flat=True)
            )
            has_active_membership = DramaAccessService.has_active_membership(request.user)
        serializer = DramaEpisodeSerializer(
            episode,
            context={
                'request': request,
                'unlocked_episode_ids': unlocked_episode_ids,
                'has_active_membership': has_active_membership,
            },
        )
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


class DramaCommentListCreateAPIView(APIView):
    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated()]
        return [AllowAny()]

    def get(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        comments = (
            DramaComment.objects.filter(series=series, parent__isnull=True, is_deleted=False)
            .select_related('user', 'parent')
            .order_by('-created_at', '-id')
        )
        paginator = DramaSeriesPagination()
        page = paginator.paginate_queryset(comments, request)
        serializer = DramaCommentSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        serializer = DramaCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent = None
        parent_id = serializer.validated_data.get('parent_id')
        if parent_id:
            parent = get_object_or_404(DramaComment.objects.filter(series=series, is_deleted=False), pk=parent_id)
        with transaction.atomic():
            comment = DramaComment.objects.create(
                series=series,
                user=request.user,
                parent=parent,
                content=serializer.validated_data['content'],
            )
            DramaSeries.objects.filter(pk=series.pk).update(comment_count=F('comment_count') + 1)
            if parent is not None:
                DramaComment.objects.filter(pk=parent.pk).update(reply_count=F('reply_count') + 1)
        comment = DramaComment.objects.select_related('user', 'parent').get(pk=comment.pk)
        return Response(DramaCommentSerializer(comment, context={'request': request}).data, status=status.HTTP_201_CREATED)


class DramaShareAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        channel = (request.data.get('channel') or '').strip()[:64]
        user = request.user if request.user.is_authenticated else None
        DramaShare.objects.create(
            user=user,
            series=series,
            channel=channel,
            ip_address=get_client_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:1000],
        )
        DramaSeries.objects.filter(pk=series.pk).update(share_count=F('share_count') + 1)
        series.refresh_from_db(fields=['share_count'])
        return Response({'series_id': series.id, 'share_count': series.share_count, 'channel': channel}, status=status.HTTP_200_OK)


class DramaInteractionSummaryAPIView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.select_related('owner').filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        return Response(DramaInteractionSummarySerializer(series, context={'request': request}).data, status=status.HTTP_200_OK)


class DramaGiftSendAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.select_related('owner').filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        if series.owner_id is None:
            return Response(
                {'code': 'drama_owner_required', 'detail': 'Drama series has no owner to receive gifts.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = GiftSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        gift = get_object_or_404(Gift, code=serializer.validated_data['gift_code'])
        cutoff = timezone.now() - timedelta(seconds=2)
        existing_tx = (
            GiftTransaction.objects.filter(
                sender=request.user,
                drama_series=series,
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
            tx = GiftService.send_drama_gift(
                sender=request.user,
                receiver=series.owner,
                drama_series=series,
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
            if 'no owner' in error_text or 'owner' in error_text:
                return Response(
                    {'code': 'drama_owner_required', 'detail': 'Drama series has no owner to receive gifts.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response({'detail': error_text}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = GiftTransactionSerializer(tx)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


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


class DramaEpisodeUnlockAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, episode_id):
        episode = get_object_or_404(
            DramaEpisode.objects.select_related('series').filter(
                is_active=True,
                series__is_active=True,
                series__status=DramaSeries.STATUS_PUBLISHED,
            ),
            pk=episode_id,
        )
        request_serializer = DramaEpisodeUnlockRequestSerializer(data=request.data or {})
        if not request_serializer.is_valid():
            return Response(
                {'code': 'invalid_payment_method', 'detail': 'Invalid payment_method.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        payment_method = request_serializer.validated_data['payment_method']
        try:
            if payment_method == 'meow_credit':
                unlock, charged = DramaAccessService.unlock_with_meow_credit(user=request.user, episode=episode)
            else:
                unlock, charged = DramaAccessService.unlock_with_meow_points(user=request.user, episode=episode)
        except DjangoValidationError as exc:
            error_text = str(exc)
            if 'Insufficient Meow Points balance.' in error_text or 'Insufficient Meow Credit balance.' in error_text:
                detail = 'Insufficient Meow Credit balance.' if payment_method == 'meow_credit' else 'Insufficient Meow Points balance.'
                return Response(
                    {'code': 'insufficient_balance', 'detail': detail},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            raise

        points_charged = episode.meow_points_price if charged and payment_method == 'meow_points' else 0
        credits_charged = episode.meow_credit_price if charged and payment_method == 'meow_credit' else 0
        payload = {
            'episode_id': episode.id,
            'series_id': episode.series_id,
            'is_unlocked': True,
            'payment_method': payment_method,
            'points_charged': points_charged,
            'credits_charged': credits_charged,
        }
        if not charged:
            payload['code'] = 'already_unlocked'
        serializer = DramaUnlockResponseSerializer(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class IsCreatorOrAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_creator or user.is_staff or user.is_superuser))


def _recount_total_episodes(series: DramaSeries):
    total = DramaEpisode.objects.filter(series=series, is_active=True).count()
    DramaSeries.objects.filter(pk=series.pk).update(total_episodes=total)


class CreatorDramaSeriesListCreateAPIView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsCreatorOrAdmin]
    serializer_class = CreatorDramaSeriesSerializer

    def get_queryset(self):
        qs = DramaSeries.objects.all().order_by('-created_at', '-id')
        if self.request.user.is_staff or self.request.user.is_superuser:
            return qs
        return qs.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class CreatorDramaSeriesDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, IsCreatorOrAdmin]
    serializer_class = CreatorDramaSeriesSerializer

    def get_queryset(self):
        qs = DramaSeries.objects.all()
        if self.request.user.is_staff or self.request.user.is_superuser:
            return qs
        return qs.filter(owner=self.request.user)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])


class CreatorDramaEpisodeListCreateAPIView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, IsCreatorOrAdmin]
    serializer_class = CreatorDramaEpisodeSerializer

    def _get_series(self):
        qs = DramaSeries.objects.all()
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            qs = qs.filter(owner=self.request.user)
        return get_object_or_404(qs, pk=self.kwargs['pk'])

    def get_queryset(self):
        series = self._get_series()
        return DramaEpisode.objects.filter(series=series).order_by('sort_order', 'episode_no', 'id')

    def perform_create(self, serializer):
        series = self._get_series()
        episode_no = serializer.validated_data.get('episode_no')
        if episode_no is not None and DramaEpisode.objects.filter(series=series, episode_no=episode_no).exists():
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'episode_no': ['Episode number already exists in this series.']})
        serializer.save(series=series)
        _recount_total_episodes(series)


class CreatorDramaEpisodeDetailAPIView(generics.UpdateAPIView, generics.DestroyAPIView):
    permission_classes = [IsAuthenticated, IsCreatorOrAdmin]
    serializer_class = CreatorDramaEpisodeSerializer
    lookup_url_kwarg = 'episode_id'

    def get_queryset(self):
        series_qs = DramaSeries.objects.all()
        if not (self.request.user.is_staff or self.request.user.is_superuser):
            series_qs = series_qs.filter(owner=self.request.user)
        series = get_object_or_404(series_qs, pk=self.kwargs['pk'])
        return DramaEpisode.objects.filter(series=series)

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
        _recount_total_episodes(instance.series)


class DramaEpisodeProgressUpsertAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, episode_id):
        episode = get_object_or_404(DramaEpisode.objects.filter(is_active=True, series__is_active=True), pk=episode_id)
        serializer = DramaProgressSaveSerializer(data={**request.data, 'episode_id': episode.id})
        serializer.is_valid(raise_exception=True)
        progress, _created = DramaWatchProgress.objects.update_or_create(
            user=request.user,
            series=episode.series,
            defaults={
                'episode': episode,
                'progress_seconds': serializer.validated_data['progress_seconds'],
                'completed': serializer.validated_data['completed'],
            },
        )
        return Response(DramaWatchProgressSerializer(progress).data)


class DramaSeriesViewTrackAPIView(APIView):
    def post(self, request, pk):
        series = get_object_or_404(
            DramaSeries.objects.filter(is_active=True, status=DramaSeries.STATUS_PUBLISHED),
            pk=pk,
        )
        now = timezone.now()
        since = now - timedelta(hours=24)
        counted = False
        with transaction.atomic():
            if request.user.is_authenticated:
                duplicate = DramaSeriesView.objects.filter(series=series, viewer=request.user, created_at__gte=since).exists()
                if not duplicate:
                    DramaSeriesView.objects.create(series=series, viewer=request.user)
                    DramaSeries.objects.filter(pk=series.pk).update(view_count=F('view_count') + 1)
                    counted = True
            else:
                if not request.session.session_key:
                    request.session.save()
                session_key = request.session.session_key or ''
                ip_address = request.META.get('REMOTE_ADDR')
                duplicate = DramaSeriesView.objects.filter(series=series, created_at__gte=since).filter(
                    Q(session_key=session_key) | Q(ip_address=ip_address)
                ).exists()
                if not duplicate:
                    DramaSeriesView.objects.create(series=series, session_key=session_key, ip_address=ip_address)
                    DramaSeries.objects.filter(pk=series.pk).update(view_count=F('view_count') + 1)
                    counted = True

        series.refresh_from_db(fields=['view_count'])
        return Response({'series_id': series.id, 'view_count': series.view_count, 'counted': counted})
