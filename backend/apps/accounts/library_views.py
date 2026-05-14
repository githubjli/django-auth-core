from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.library_serializers import (
    LibraryGiftItemSerializer,
    LibraryHistoryItemSerializer,
    LibraryLikedItemSerializer,
    LibraryPurchasedItemSerializer,
)
from apps.accounts.models import (
    DramaUnlock,
    DramaWatchProgress,
    GiftTransaction,
    PaymentOrder,
    UserMembership,
    VideoLike,
    VideoView,
)


class LibraryPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class LibraryListAPIView(APIView):
    permission_classes = [IsAuthenticated]
    pagination_class = LibraryPagination
    serializer_class = None

    def get_items(self, request):
        raise NotImplementedError

    def get(self, request, *args, **kwargs):
        items = self.get_items(request)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(items, request, view=self)
        serializer = self.serializer_class(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    def build_file_url(self, request, file_field):
        if not file_field:
            return None
        url = file_field.url
        return request.build_absolute_uri(url)

    def user_summary(self, user):
        if user is None:
            return {'id': None, 'name': None}
        return {'id': user.id, 'name': user.display_name}

    def gift_amounts(self, gift):
        amount = gift.amount or gift.total_points
        points_amount = gift.points_amount or gift.total_points
        return {
            'amount': amount,
            'points_amount': points_amount,
            'credits_amount': gift.credits_amount,
        }

    def gift_content(self, gift):
        if gift.video_id and gift.video is not None:
            return {'type': 'video', 'id': gift.video.id, 'title': gift.video.title}
        if gift.drama_series_id and gift.drama_series is not None:
            return {'type': 'drama', 'id': gift.drama_series.id, 'title': gift.drama_series.title}
        if gift.stream_id and gift.stream is not None:
            return {'type': 'live_stream', 'id': gift.stream.id, 'title': gift.stream.title}

        content_type = ''
        if gift.target_type == GiftTransaction.TARGET_VIDEO:
            content_type = 'video'
        elif gift.target_type == GiftTransaction.TARGET_DRAMA_SERIES:
            content_type = 'drama'
        elif gift.target_type == GiftTransaction.TARGET_LIVE_STREAM:
            content_type = 'live_stream'

        return {'type': content_type or None, 'id': gift.target_id, 'title': ''}


class AccountLibraryHistoryAPIView(LibraryListAPIView):
    serializer_class = LibraryHistoryItemSerializer

    def get_items(self, request):
        drama_progress = (
            DramaWatchProgress.objects
            .filter(user=request.user)
            .select_related('series', 'episode')
        )
        video_views = (
            VideoView.objects
            .filter(viewer=request.user)
            .select_related('video')
        )

        items = []
        for progress in drama_progress:
            items.append({
                'type': 'drama',
                'id': progress.series_id,
                'title': progress.series.title,
                'cover_url': self.build_file_url(request, progress.series.cover),
                'series_id': progress.series_id,
                'episode_id': progress.episode_id,
                'episode_no': progress.episode.episode_no,
                'progress_seconds': progress.progress_seconds,
                'duration_seconds': progress.episode.duration_seconds,
                'updated_at': progress.updated_at,
            })

        for view in video_views:
            items.append({
                'type': 'video',
                'id': view.video_id,
                'title': view.video.title,
                'thumbnail_url': self.build_file_url(request, view.video.thumbnail),
                'progress_seconds': 0,
                'duration_seconds': 0,
                'updated_at': view.created_at,
            })

        return sorted(items, key=lambda item: item['updated_at'], reverse=True)


class AccountLibraryLikedAPIView(LibraryListAPIView):
    serializer_class = LibraryLikedItemSerializer

    def get_items(self, request):
        likes = (
            VideoLike.objects
            .filter(user=request.user)
            .select_related('video')
            .order_by('-created_at', '-id')
        )
        return [
            {
                'type': 'video',
                'id': like.video_id,
                'title': like.video.title,
                'thumbnail_url': self.build_file_url(request, like.video.thumbnail),
                'liked_at': like.created_at,
            }
            for like in likes
        ]


class AccountLibraryPurchasedAPIView(LibraryListAPIView):
    serializer_class = LibraryPurchasedItemSerializer

    def get_items(self, request):
        unlocks = (
            DramaUnlock.objects
            .filter(user=request.user)
            .select_related('series', 'episode')
        )
        orders = PaymentOrder.objects.filter(user=request.user).select_related('product')
        memberships = UserMembership.objects.filter(user=request.user).select_related('plan')

        items = []
        for unlock in unlocks:
            items.append({
                'type': 'drama_episode',
                'id': unlock.episode_id,
                'series_id': unlock.series_id,
                'title': unlock.episode.title,
                'cover_url': self.build_file_url(request, unlock.series.cover),
                'source': 'unlock',
                'payment_method': unlock.source,
                'purchased_at': unlock.unlocked_at,
            })

        for order in orders:
            title = order.plan_name_snapshot or 'Payment order'
            if order.product_id and order.product is not None:
                title = order.product.title
            items.append({
                'type': 'order',
                'id': order.id,
                'title': title,
                'amount': order.amount,
                'currency': order.currency,
                'status': order.status,
                'purchased_at': order.paid_at or order.created_at,
            })

        for membership in memberships:
            items.append({
                'type': 'membership',
                'id': membership.id,
                'title': membership.plan.name if membership.plan_id else 'Membership',
                'status': membership.status,
                'starts_at': membership.starts_at,
                'ends_at': membership.ends_at,
                'purchased_at': membership.created_at,
            })

        return sorted(items, key=lambda item: item['purchased_at'], reverse=True)


class AccountLibraryGiftsSentAPIView(LibraryListAPIView):
    serializer_class = LibraryGiftItemSerializer

    def get_items(self, request):
        gifts = (
            GiftTransaction.objects
            .filter(sender=request.user)
            .select_related('receiver', 'video', 'drama_series', 'stream', 'gift')
            .order_by('-created_at', '-id')
        )
        return [
            {
                'id': gift.id,
                'direction': 'sent',
                'gift_name': gift.gift_name_snapshot or (gift.gift.name if gift.gift_id else ''),
                **self.gift_amounts(gift),
                'receiver': self.user_summary(gift.receiver),
                'content': self.gift_content(gift),
                'created_at': gift.created_at,
            }
            for gift in gifts
        ]


class AccountLibraryGiftsReceivedAPIView(LibraryListAPIView):
    serializer_class = LibraryGiftItemSerializer

    def get_items(self, request):
        gifts = (
            GiftTransaction.objects
            .filter(receiver=request.user)
            .select_related('sender', 'video', 'drama_series', 'stream', 'gift')
            .order_by('-created_at', '-id')
        )
        return [
            {
                'id': gift.id,
                'direction': 'received',
                'gift_name': gift.gift_name_snapshot or (gift.gift.name if gift.gift_id else ''),
                **self.gift_amounts(gift),
                'sender': self.user_summary(gift.sender),
                'content': self.gift_content(gift),
                'created_at': gift.created_at,
            }
            for gift in gifts
        ]
