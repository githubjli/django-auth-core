from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify
from django.utils.dateparse import parse_date
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, Exists, F, IntegerField, OuterRef, Q, Value, When
from datetime import timedelta
from decimal import Decimal
import json
import hashlib
import hmac
import logging
import secrets
import threading
from asgiref.sync import async_to_sync
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.constants import TOKEN_SYMBOL
from apps.accounts.models import (
    BillingPlan,
    BillingSubscription,
    Category,
    Gift,
    GiftTransaction,
    DramaSeries,
    ChannelSubscription,
    CommentLike,
    LiveChatMessage,
    LiveChatRoom,
    LiveStream,
    LiveStreamProduct,
    ManualMembershipPayment,
    MembershipPlan,
    MeowCreditLedger,
    MeowCreditWallet,
    MeowPointLedger,
    MeowPointWallet,
    PaymentOrder,
    Product,
    ProductCategory,
    ProductOrder,
    ProductRefundRequest,
    SellerApplication,
    SellerPayout,
    SellerPayoutAddress,
    SellerStore,
    ShopBanner,
    SavedProduct,
    StreamPaymentMethod,
    UserShippingAddress,
    UserMembership,
    Video,
    VideoComment,
    VideoLike,
    VideoShare,
    VideoView,
    generate_stream_key,
)
from apps.accounts.permissions import IsCreator, IsStaffOrSuperuser
from apps.accounts.gift_serializers import ContentGiftSendResponseSerializer, ContentGiftSendSerializer, GiftSendSerializer, GiftTransactionSerializer
from apps.accounts.serializers import (
    AccountPasswordChangeSerializer,
    AccountPreferencesSerializer,
    AccountProfileSerializer,
    AdminUserSerializer,
    AdminVideoSerializer,
    BillingPlanSerializer,
    BillingSubscriptionCreateSerializer,
    BillingSubscriptionSerializer,
    ManualMembershipPaymentHintSerializer,
    ManualMembershipTxHintSubmitSerializer,
    MembershipOrderCreateSerializer,
    MembershipOrderTxHintSerializer,
    MembershipOrderSerializer,
    MembershipPlanSerializer,
    MobileShippingAddressSerializer,
    MyMembershipSerializer,
    WalletPrototypePayOrderSerializer,
    WalletPrototypePayProductOrderSerializer,
    LiveStreamSerializer,
    LiveStreamProductListingSerializer,
    LiveStreamProductManageCreateSerializer,
    LiveStreamProductManageUpdateSerializer,
    LiveChatMessageCreateSerializer,
    LiveChatMessageSerializer,
    EmailTokenObtainPairSerializer,
    PublicCategorySerializer,
    ProductSerializer,
    ProductOrderCreateSerializer,
    ProductOrderDetailSerializer,
    PaymentQRResolveSerializer,
    ProductOrderMarkSettledSerializer,
    ProductOrderShipSerializer,
    ProductShipmentSerializer,
    ProductOrderTxHintSerializer,
    ProductCategorySerializer,
    ProductRefundAdminActionSerializer,
    ProductRefundRequestCreateSerializer,
    ProductRefundRequestSerializer,
    AdminSellerApplicationSerializer,
    SellerApplicationRejectSerializer,
    SellerApplicationSerializer,
    SellerPayoutAddressSerializer,
    SellerProductOrderListSerializer,
    PaymentOrderCreateSerializer,
    PaymentOrderSerializer,
    PublicCreatorSerializer,
    PublicUserListItemSerializer,
    PublicUserProfileSerializer,
    RegisterSerializer,
    SavedProductSerializer,
    AddSavedProductSerializer,
    ShopBannerSerializer,
    ShopProductListSerializer,
    SellerStoreSerializer,
    UserShippingAddressSerializer,
    StreamPaymentMethodSerializer,
    UserSerializer,
    VideoCommentCreateSerializer,
    VideoCommentSerializer,
    VideoInteractionSummarySerializer,
    VideoMetadataSerializer,
    VideoSerializer,
)
from apps.accounts.drama_serializers import DramaSeriesSerializer
from apps.accounts.services import (
    approve_seller_application,
    AntMediaLiveAdapter,
    LbryDaemonConnectionError,
    LbryDaemonError,
    LbryDaemonInvalidParamsError,
    LbryDaemonRpcError,
    ManualMembershipChainVerifier,
    MembershipActivationService,
    MembershipOrderService,
    ProductOrderService,
    ProductPaymentDetectionService,
    sign_product_qr_payload,
    verify_product_qr_signature,
    MembershipOrderPersistenceError,
    PaymentDetectionService,
    WalletPrototypeError,
    WalletPrototypeValidationError,
    WalletPrototypePayOrderService,
    get_product_wallet_send_amount,
    WalletAddressConflictError,
    generate_video_thumbnail,
    MeowPointService,
    GiftService,
    follow_user,
    unfollow_user,
    create_live_chat_message,
    capture_live_snapshot,
)

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


LIVE_OWNER_PERMISSION_DETAIL = 'Only the live owner can perform this action.'


class IsCreatorOrStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        return bool(
            user
            and user.is_authenticated
            and (user.is_creator or user.is_staff or user.is_superuser)
        )


def live_owner_forbidden_response():
    return Response(
        {'detail': LIVE_OWNER_PERMISSION_DETAIL},
        status=status.HTTP_403_FORBIDDEN,
    )


def publish_config_error_response(*, live_payload, error=None, message=None):
    return Response(
        {
            'detail': 'Publish config unavailable.',
            'error': error or 'ant_media_publish_config_unavailable',
            'live': live_payload,
            'publish_config': {
                'ok': False,
                'error': error or 'ant_media_publish_config_unavailable',
                'message': message or 'Publish config unavailable.',
            },
            'next_action': 'retry_prepare',
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def get_client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip() or None
    return request.META.get('REMOTE_ADDR') or None


def annotate_videos_for_request(queryset, request):
    queryset = queryset.select_related('owner', 'category').annotate(
        view_count=Count('views', distinct=True),
        owner_follower_count=Count('owner__subscriptions_received', distinct=True),
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


def sync_user_follower_count(user):
    follower_count = ChannelSubscription.objects.filter(channel=user).count()
    User.objects.filter(pk=user.pk).update(subscriber_count=follower_count)
    user.subscriber_count = follower_count
    return follower_count


def set_user_following(target_user, viewer, is_following):
    if is_following:
        ChannelSubscription.objects.get_or_create(channel=target_user, subscriber=viewer)
    else:
        ChannelSubscription.objects.filter(channel=target_user, subscriber=viewer).delete()
    return sync_user_follower_count(target_user)


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


def build_membership_purchase_preview(user, plan: MembershipPlan) -> dict:
    now = timezone.now()
    current = (
        UserMembership.objects.filter(
            user=user,
            status=UserMembership.STATUS_ACTIVE,
            starts_at__lte=now,
            ends_at__gt=now,
        )
        .select_related('plan')
        .order_by('-ends_at', '-id')
        .first()
    )

    if current is None:
        starts_at = now
        purchase_mode = 'new'
        current_membership = None
    else:
        starts_at = current.ends_at
        purchase_mode = 'renewal' if current.plan_id == plan.id else 'plan_change'
        current_membership = {
            'plan_code': current.plan.code,
            'plan_name': current.plan.name,
            'starts_at': current.starts_at,
            'ends_at': current.ends_at,
        }

    ends_at = starts_at + timedelta(days=plan.duration_days)
    return {
        'has_active_membership': current is not None,
        'current_membership': current_membership,
        'purchase_mode': purchase_mode,
        'is_renewal': purchase_mode == 'renewal',
        'is_plan_change': purchase_mode == 'plan_change',
        'estimated_new_starts_at': starts_at,
        'estimated_new_ends_at': ends_at,
    }


class PaymentOrderPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class RegisterAPIView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]


class LoginAPIView(TokenObtainPairView):
    serializer_class = EmailTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code != status.HTTP_200_OK:
            return response

        user = authenticate(request=request, email=request.data.get('email'), password=request.data.get('password'))
        if user is None:
            return response
        try:
            reward_result = MeowPointService.grant_daily_login_reward(user=user)
            response.data['daily_login_reward'] = reward_result
        except Exception:
            logger.exception('Failed to grant daily login reward', extra={'user_id': user.id})
        return response


class RefreshAPIView(TokenRefreshView):
    permission_classes = [permissions.AllowAny]


class MeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user, context={'request': request})
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


class AccountPasswordChangeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        serializer = AccountPasswordChangeSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password'])
        return Response({'detail': 'Password updated successfully.'}, status=status.HTTP_200_OK)


class AccountPaymentOrderListAPIView(generics.ListAPIView):
    serializer_class = PaymentOrderSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = PaymentOrderPagination

    def get_queryset(self):
        queryset = PaymentOrder.objects.filter(user=self.request.user).select_related(
            'stream',
            'product',
            'payment_method',
            'paid_by',
        )

        status_filter = self.request.query_params.get('status')
        if status_filter in {choice for choice, _ in PaymentOrder.STATUS_CHOICES}:
            queryset = queryset.filter(status=status_filter)

        stream_id = self.request.query_params.get('live_stream')
        if stream_id and str(stream_id).isdigit():
            queryset = queryset.filter(stream_id=int(stream_id))

        product_id = self.request.query_params.get('product')
        if product_id and str(product_id).isdigit():
            queryset = queryset.filter(product_id=int(product_id))

        date_from = parse_date(self.request.query_params.get('date_from') or '')
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)

        date_to = parse_date(self.request.query_params.get('date_to') or '')
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        return queryset


class AccountShippingAddressListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = UserShippingAddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return UserShippingAddress.objects.filter(user=self.request.user)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class AccountShippingAddressDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = UserShippingAddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        return UserShippingAddress.objects.filter(user=self.request.user)

    def perform_destroy(self, instance):
        was_default = instance.is_default
        user = instance.user
        instance.delete()
        if was_default:
            next_address = UserShippingAddress.objects.filter(user=user).order_by('-updated_at', '-id').first()
            if next_address:
                next_address.is_default = True
                next_address.save(update_fields=['is_default', 'updated_at'])


class ShippingAddressListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = MobileShippingAddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return UserShippingAddress.objects.filter(user=self.request.user)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context


class ShippingAddressDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MobileShippingAddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        return UserShippingAddress.objects.filter(user=self.request.user)

    def perform_destroy(self, instance):
        was_default = instance.is_default
        user = instance.user
        instance.delete()
        if was_default:
            next_address = UserShippingAddress.objects.filter(user=user).order_by('-updated_at', '-id').first()
            if next_address:
                next_address.is_default = True
                next_address.save(update_fields=['is_default', 'updated_at'])


class ProductOrderListCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def get(self, request):
        queryset = ProductOrder.objects.filter(buyer=request.user).select_related(
            'payment_order',
            'product',
            'seller_store',
            'shipment',
            'seller_payout',
        )
        status_filter = request.query_params.get('status')
        valid_statuses = {choice for choice, _ in ProductOrder.STATUS_CHOICES}
        if status_filter in valid_statuses:
            queryset = queryset.filter(status=status_filter)
        serializer = ProductOrderDetailSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ProductOrderCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        service = ProductOrderService()
        try:
            order = service.create_order_with_asset(
                buyer=request.user,
                product=serializer.validated_data['product'],
                quantity=serializer.validated_data['quantity'],
                shipping_address=serializer.validated_data['shipping_address'],
                payment_asset=serializer.validated_data['payment_asset'],
            )
        except RuntimeError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        response_serializer = ProductOrderDetailSerializer(order)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class ProductOrderDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, order_no):
        order = generics.get_object_or_404(
            ProductOrder.objects.select_related('payment_order', 'shipment', 'seller_payout'),
            order_no=order_no,
            buyer=request.user,
        )
        serializer = ProductOrderDetailSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ProductOrderCancelAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request, order_no):
        order = generics.get_object_or_404(
            ProductOrder.objects.select_related('payment_order', 'product', 'seller_store', 'shipment', 'seller_payout'),
            order_no=order_no,
            buyer=request.user,
        )
        try:
            order = ProductOrderService().cancel_order(order=order, reason=request.data.get('reason', '') or '')
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        order = ProductOrder.objects.select_related(
            'payment_order',
            'product',
            'seller_store',
            'shipment',
            'seller_payout',
        ).prefetch_related('refund_requests').get(pk=order.pk)
        return Response(ProductOrderDetailSerializer(order).data, status=status.HTTP_200_OK)


class ProductOrderTrackingAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, order_no):
        order = generics.get_object_or_404(
            ProductOrder.objects.select_related('shipment'),
            order_no=order_no,
            buyer=request.user,
        )
        shipment = getattr(order, 'shipment', None)
        timeline = []
        if order.paid_at:
            timeline.append({'status': 'paid', 'time': order.paid_at})
        if order.shipped_at:
            timeline.append({'status': 'shipped', 'time': order.shipped_at})
        if order.completed_at:
            timeline.append({'status': 'completed', 'time': order.completed_at})
        return Response(
            {
                'order_no': order.order_no,
                'status': order.status,
                'shipment': ProductShipmentSerializer(shipment).data if shipment else None,
                'timeline': timeline if shipment else [],
            },
            status=status.HTTP_200_OK,
        )


class SellerProductOrderListAPIView(generics.ListAPIView):
    serializer_class = SellerProductOrderListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        queryset = ProductOrder.objects.select_related('buyer', 'payment_order', 'shipment', 'seller_payout').filter(
            seller_store__owner=self.request.user
        ).order_by('-created_at', '-id')
        status_filter = self.request.query_params.get('status')
        if status_filter in {choice for choice, _ in ProductOrder.STATUS_CHOICES}:
            queryset = queryset.filter(status=status_filter)
        date_from = parse_date(self.request.query_params.get('date_from') or '')
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        date_to = parse_date(self.request.query_params.get('date_to') or '')
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        search = (self.request.query_params.get('search') or '').strip()
        if search:
            queryset = queryset.filter(Q(order_no__icontains=search) | Q(product_title_snapshot__icontains=search))
        return queryset


class SellerProductOrderDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, order_no):
        order = generics.get_object_or_404(
            ProductOrder.objects.select_related('buyer', 'payment_order', 'shipment', 'seller_payout'),
            order_no=order_no,
            seller_store__owner=request.user,
        )
        return Response(SellerProductOrderListSerializer(order).data, status=status.HTTP_200_OK)


class ProductOrderTxHintAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request, order_no):
        base_qs = ProductOrder.objects.select_related('payment_order')
        if request.user.is_staff or request.user.is_superuser:
            order = generics.get_object_or_404(base_qs, order_no=order_no)
        else:
            order = generics.get_object_or_404(base_qs, order_no=order_no, buyer=request.user)
        serializer = ProductOrderTxHintSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        txid = serializer.validated_data['txid'].strip()
        payment_order = order.payment_order
        if payment_order is None:
            return Response({'verified': False, 'matched': False, 'paid': False, 'status': '', 'confirmations': 0, 'txid': '', 'product_order_status': order.status}, status=status.HTTP_200_OK)
        payment_order.txid = txid
        payment_order.save(update_fields=['txid', 'updated_at'])
        verification = ProductPaymentDetectionService().verify_product_order_once(order=payment_order, txid_hint=txid)
        return Response(verification, status=status.HTTP_200_OK)


class PaymentQRResolveAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        serializer = PaymentQRResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw_payload = (serializer.validated_data.get('payload') or '').strip()
        try:
            payload = json.loads(raw_payload)
        except json.JSONDecodeError:
            return Response({'detail': 'Invalid QR payload format.'}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(payload, dict):
            return Response({'detail': 'Invalid QR payload format.'}, status=status.HTTP_400_BAD_REQUEST)

        is_short_payload = {'v', 't', 'o', 's'}.issubset(payload.keys())
        is_legacy_payload = {'version', 'type', 'order_no', 'sig'}.issubset(payload.keys())
        if is_short_payload:
            payload_type = str(payload.get('t') or '')
            order_no = str(payload.get('o') or '').strip()
            provided_sig = str(payload.get('s') or '')
            if int(payload.get('v') or 0) != 1 or payload_type != 'product_payment' or not order_no:
                return Response({'detail': 'Unsupported QR payload type.'}, status=status.HTTP_400_BAD_REQUEST)
        elif is_legacy_payload:
            payload_type = str(payload.get('type') or '')
            order_no = str(payload.get('order_no') or '').strip()
            provided_sig = str(payload.get('sig') or '')
            if int(payload.get('version') or 0) != 1 or payload_type != 'product_payment' or not order_no:
                return Response({'detail': 'Unsupported QR payload type.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'detail': 'Unsupported QR payload type.'}, status=status.HTTP_400_BAD_REQUEST)

        order = ProductOrder.objects.select_related('payment_order').filter(order_no=order_no).first()
        if order is None or order.payment_order is None or order.payment_order.order_type != PaymentOrder.TYPE_PRODUCT:
            return Response({'detail': 'Unsupported QR payload type.'}, status=status.HTTP_400_BAD_REQUEST)
        payment_order = order.payment_order
        if payment_order.expires_at and payment_order.expires_at <= timezone.now():
            return Response({'detail': 'Payment order has expired.'}, status=status.HTTP_400_BAD_REQUEST)

        expires_at_iso = payment_order.expires_at.isoformat() if payment_order.expires_at else ''
        expected_amount = str(payment_order.expected_amount_lbc if payment_order.expected_amount_lbc is not None else order.total_amount)
        expected_sig = sign_product_qr_payload(
            version=1,
            payload_type='product_payment',
            order_no=order.order_no,
            pay_to_address=payment_order.pay_to_address or '',
            expected_amount=expected_amount,
            currency=order.currency,
            expires_at=expires_at_iso,
        )
        if is_short_payload:
            signature_valid = bool(provided_sig) and hmac.compare_digest(provided_sig, expected_sig)
        else:
            signature_valid = verify_product_qr_signature(payload) and hmac.compare_digest(str(payload.get('sig') or ''), expected_sig)
        if not signature_valid:
            return Response({'detail': 'Invalid QR signature.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                'type': 'product_payment',
                'order_no': order.order_no,
                'product_title': order.product_title_snapshot,
                'expected_amount': expected_amount,
                'currency': order.currency,
                'pay_to_address': payment_order.pay_to_address,
                'expires_at': payment_order.expires_at,
                'payment_status': payment_order.status,
                'txid': payment_order.txid,
                'confirmations': payment_order.confirmations,
            },
            status=status.HTTP_200_OK,
        )


class ProductOrderMarkPaidAPIView(APIView):
    permission_classes = [IsStaffOrSuperuser]

    def post(self, request, order_no):
        order = generics.get_object_or_404(ProductOrder.objects.select_related('payment_order'), order_no=order_no)
        try:
            ProductOrderService().mark_paid(order=order)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ProductOrderDetailSerializer(order).data, status=status.HTTP_200_OK)


class SellerProductOrderShipAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request, order_no):
        order = generics.get_object_or_404(
            ProductOrder.objects.select_related('seller_store', 'shipment'),
            order_no=order_no,
            seller_store__owner=request.user,
        )
        serializer = ProductOrderShipSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ProductOrderService().ship_order(
                order=order,
                created_by=request.user,
                carrier=serializer.validated_data['carrier'],
                tracking_number=serializer.validated_data['tracking_number'],
                tracking_url=serializer.validated_data.get('tracking_url') or '',
                shipped_note=serializer.validated_data.get('shipped_note') or '',
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ProductOrderDetailSerializer(order).data, status=status.HTTP_200_OK)


class ProductOrderConfirmReceivedAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_no):
        order = generics.get_object_or_404(
            ProductOrder.objects.select_related('seller_payout'),
            order_no=order_no,
            buyer=request.user,
        )
        try:
            ProductOrderService().confirm_received(order=order)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        order.refresh_from_db()
        return Response(ProductOrderDetailSerializer(order).data, status=status.HTTP_200_OK)


class SellerPayoutAddressListCreateAPIView(generics.ListCreateAPIView):
    serializer_class = SellerPayoutAddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        return SellerPayoutAddress.objects.filter(seller_store__owner=self.request.user, is_active=True)

    def perform_create(self, serializer):
        store = generics.get_object_or_404(SellerStore, owner=self.request.user, is_active=True)
        is_first = not SellerPayoutAddress.objects.filter(seller_store=store, is_active=True).exists()
        is_default = serializer.validated_data.get('is_default', False) or is_first
        if is_default:
            SellerPayoutAddress.objects.filter(seller_store=store, is_default=True).update(is_default=False)
        serializer.save(seller_store=store, is_default=is_default)


class SellerPayoutAddressDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SellerPayoutAddressSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        return SellerPayoutAddress.objects.filter(seller_store__owner=self.request.user)

    def perform_update(self, serializer):
        instance = self.get_object()
        is_default = serializer.validated_data.get('is_default')
        if is_default:
            SellerPayoutAddress.objects.filter(seller_store=instance.seller_store, is_default=True).exclude(id=instance.id).update(is_default=False)
        serializer.save()

    def perform_destroy(self, instance):
        instance.is_active = False
        if instance.is_default:
            instance.is_default = False
        instance.save(update_fields=['is_active', 'is_default', 'updated_at'])


class ProductRefundRequestListCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def get(self, request, order_no):
        order = generics.get_object_or_404(ProductOrder, order_no=order_no, buyer=request.user)
        queryset = ProductRefundRequest.objects.filter(product_order=order)
        return Response(ProductRefundRequestSerializer(queryset, many=True).data, status=status.HTTP_200_OK)

    def post(self, request, order_no):
        order = generics.get_object_or_404(ProductOrder, order_no=order_no, buyer=request.user)
        if order.status not in {ProductOrder.STATUS_PAID, ProductOrder.STATUS_SHIPPING, ProductOrder.STATUS_COMPLETED}:
            return Response({'detail': 'Refund request not allowed for current order status.'}, status=status.HTTP_400_BAD_REQUEST)
        active_exists = ProductRefundRequest.objects.filter(
            product_order=order,
            status__in=[ProductRefundRequest.STATUS_REQUESTED, ProductRefundRequest.STATUS_APPROVED],
        ).exists()
        if active_exists:
            return Response({'detail': 'Active refund request already exists for this order.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ProductRefundRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        requested_amount = serializer.validated_data.get('requested_amount') or order.total_amount
        refund = ProductRefundRequest.objects.create(
            product_order=order,
            requester=request.user,
            reason=serializer.validated_data['reason'],
            requested_amount=requested_amount,
            currency=order.currency,
        )
        return Response(ProductRefundRequestSerializer(refund).data, status=status.HTTP_201_CREATED)


class SellerRefundRequestListAPIView(generics.ListAPIView):
    serializer_class = ProductRefundRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        queryset = ProductRefundRequest.objects.select_related('product_order').filter(
            product_order__seller_store__owner=self.request.user
        ).order_by('-created_at', '-id')
        status_filter = self.request.query_params.get('status')
        if status_filter in {choice for choice, _ in ProductRefundRequest.STATUS_CHOICES}:
            queryset = queryset.filter(status=status_filter)
        date_from = parse_date(self.request.query_params.get('date_from') or '')
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        date_to = parse_date(self.request.query_params.get('date_to') or '')
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)
        return queryset


class AdminRefundRequestListAPIView(generics.ListAPIView):
    serializer_class = ProductRefundRequestSerializer
    permission_classes = [IsStaffOrSuperuser]
    pagination_class = None
    queryset = ProductRefundRequest.objects.select_related('product_order', 'requester').order_by('-created_at', '-id')


class AdminRefundRequestApproveAPIView(APIView):
    permission_classes = [IsStaffOrSuperuser]
    parser_classes = [JSONParser, FormParser]

    def post(self, request, pk):
        refund = generics.get_object_or_404(ProductRefundRequest, pk=pk)
        if refund.status != ProductRefundRequest.STATUS_REQUESTED:
            return Response({'detail': 'Only requested refunds can be approved.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ProductRefundAdminActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund.status = ProductRefundRequest.STATUS_APPROVED
        refund.admin_note = serializer.validated_data.get('admin_note') or ''
        refund.resolved_at = None
        refund.save(update_fields=['status', 'admin_note', 'resolved_at', 'updated_at'])
        return Response(ProductRefundRequestSerializer(refund).data, status=status.HTTP_200_OK)


class AdminRefundRequestRejectAPIView(APIView):
    permission_classes = [IsStaffOrSuperuser]
    parser_classes = [JSONParser, FormParser]

    def post(self, request, pk):
        refund = generics.get_object_or_404(ProductRefundRequest, pk=pk)
        if refund.status not in {ProductRefundRequest.STATUS_REQUESTED, ProductRefundRequest.STATUS_APPROVED}:
            return Response({'detail': 'Only requested/approved refunds can be rejected.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ProductRefundAdminActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        refund.status = ProductRefundRequest.STATUS_REJECTED
        refund.admin_note = serializer.validated_data.get('admin_note') or ''
        refund.resolved_at = timezone.now()
        refund.save(update_fields=['status', 'admin_note', 'resolved_at', 'updated_at'])
        return Response(ProductRefundRequestSerializer(refund).data, status=status.HTTP_200_OK)


class AdminRefundRequestMarkRefundedAPIView(APIView):
    permission_classes = [IsStaffOrSuperuser]
    parser_classes = [JSONParser, FormParser]

    def post(self, request, pk):
        refund = generics.get_object_or_404(ProductRefundRequest.objects.select_related('product_order'), pk=pk)
        if refund.status not in {ProductRefundRequest.STATUS_REQUESTED, ProductRefundRequest.STATUS_APPROVED}:
            return Response({'detail': 'Only requested/approved refunds can be marked refunded.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ProductRefundAdminActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = refund.product_order
        if refund.refunded_asset_transaction_id is not None:
            return Response(ProductRefundRequestSerializer(refund).data, status=status.HTTP_200_OK)
        if order.status == ProductOrder.STATUS_SETTLED:
            return Response({'detail': 'Settled orders cannot be auto-refunded.'}, status=status.HTTP_400_BAD_REQUEST)
        payout = getattr(order, 'seller_payout', None)
        if payout and payout.status == SellerPayout.STATUS_PENDING:
            payout.status = SellerPayout.STATUS_FAILED
            payout.failure_note = 'refund_marked'
            payout.save(update_fields=['status', 'failure_note', 'updated_at'])
        if order.payment_method == ProductOrder.PAYMENT_METHOD_PLATFORM_ASSET and order.payment_asset:
            refund_amount = refund.requested_amount
            with transaction.atomic():
                amount = Decimal(str(refund_amount)).quantize(Decimal('0.01'))
                if order.payment_asset == ProductOrder.ASSET_MEOW_POINTS:
                    wallet = MeowPointWallet.objects.select_for_update().get_or_create(user=order.buyer)[0]
                    before = Decimal(str(wallet.balance))
                    after = (before + amount).quantize(Decimal('0.01'))
                    wallet.balance = after
                    wallet.total_earned = (Decimal(str(wallet.total_earned)) + amount).quantize(Decimal('0.01'))
                    wallet.save(update_fields=['balance', 'total_earned', 'updated_at'])
                    MeowPointLedger.objects.create(
                        user=order.buyer,
                        entry_type=MeowPointLedger.TYPE_REFUND,
                        amount=amount,
                        balance_before=before,
                        balance_after=after,
                        target_type='product_refund',
                        target_id=refund.id,
                        note='product_refund',
                    )
                else:
                    wallet = MeowCreditWallet.objects.select_for_update().get_or_create(user=order.buyer)[0]
                    before = Decimal(str(wallet.balance))
                    after = (before + amount).quantize(Decimal('0.01'))
                    wallet.balance = after
                    wallet.save(update_fields=['balance', 'updated_at'])
                    MeowCreditLedger.objects.create(
                        user=order.buyer,
                        entry_type=MeowCreditLedger.TYPE_REFUND,
                        status=MeowCreditLedger.STATUS_COMPLETED,
                        amount=amount,
                        balance_before=before,
                        balance_after=after,
                        target_type='product_refund',
                        target_id=refund.id,
                        note='product_refund',
                    )
                refund.refunded_asset_transaction = None
        refund.status = ProductRefundRequest.STATUS_REFUNDED
        refund.admin_note = serializer.validated_data.get('admin_note') or ''
        refund.refund_txid = serializer.validated_data.get('refund_txid') or ''
        refund.resolved_at = timezone.now()
        refund.save(update_fields=['status', 'admin_note', 'refund_txid', 'resolved_at', 'updated_at'])
        return Response(ProductRefundRequestSerializer(refund).data, status=status.HTTP_200_OK)


class AdminProductOrderMarkSettledAPIView(APIView):
    permission_classes = [IsStaffOrSuperuser]
    parser_classes = [JSONParser, FormParser]

    def post(self, request, order_no):
        order = generics.get_object_or_404(ProductOrder.objects.select_related('seller_payout'), order_no=order_no)
        serializer = ProductOrderMarkSettledSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            ProductOrderService().mark_settled(
                order=order,
                txid=serializer.validated_data.get('txid') or '',
                payout_address=serializer.validated_data.get('payout_address') or '',
                note=serializer.validated_data.get('note') or '',
            )
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        order.refresh_from_db()
        return Response(ProductOrderDetailSerializer(order).data, status=status.HTTP_200_OK)



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


class SellerApplicationCreateAPIView(generics.CreateAPIView):
    serializer_class = SellerApplicationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        if SellerStore.objects.filter(owner=request.user).exists():
            return Response({'detail': 'User is already a seller.'}, status=status.HTTP_409_CONFLICT)
        if SellerApplication.objects.filter(user=request.user, status=SellerApplication.STATUS_PENDING).exists():
            return Response({'detail': 'Pending seller application already exists.'}, status=status.HTTP_409_CONFLICT)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SellerApplicationMeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        application = SellerApplication.objects.filter(user=request.user).order_by('-submitted_at', '-id').first()
        if application is None:
            return Response({'detail': 'Seller application not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = SellerApplicationSerializer(application, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class AdminSellerApplicationListAPIView(generics.ListAPIView):
    serializer_class = AdminSellerApplicationSerializer
    permission_classes = [IsStaffOrSuperuser]

    def get_queryset(self):
        queryset = SellerApplication.objects.select_related('user', 'reviewed_by').order_by('-submitted_at', '-id')
        status_filter = self.request.query_params.get('status')
        if status_filter in {choice for choice, _ in SellerApplication.STATUS_CHOICES}:
            queryset = queryset.filter(status=status_filter)
        return queryset


class AdminSellerApplicationApproveAPIView(APIView):
    permission_classes = [IsStaffOrSuperuser]

    def post(self, request, pk):
        application = generics.get_object_or_404(SellerApplication, pk=pk)
        try:
            application, store = approve_seller_application(application, reviewer=request.user)
        except ValueError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        response_data = {
            'application': AdminSellerApplicationSerializer(application, context={'request': request}).data,
            'store': SellerStoreSerializer(store, context={'request': request}).data,
        }
        return Response(response_data, status=status.HTTP_200_OK)


class AdminSellerApplicationRejectAPIView(APIView):
    permission_classes = [IsStaffOrSuperuser]

    @transaction.atomic
    def post(self, request, pk):
        application = generics.get_object_or_404(
            SellerApplication.objects.select_for_update().select_related('user', 'reviewed_by'),
            pk=pk,
        )
        if application.status == SellerApplication.STATUS_APPROVED:
            return Response({'detail': 'Approved seller application cannot be rejected.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = SellerApplicationRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application.status = SellerApplication.STATUS_REJECTED
        application.rejection_reason = serializer.validated_data['rejection_reason']
        application.reviewed_by = request.user
        application.reviewed_at = timezone.now()
        application.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at', 'updated_at'])
        response_serializer = AdminSellerApplicationSerializer(application, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_200_OK)


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
        approved_application = SellerApplication.objects.filter(
            user=request.user,
            status=SellerApplication.STATUS_APPROVED,
        ).order_by('-reviewed_at', '-submitted_at', '-id').first()
        if approved_application is None:
            return Response(
                {'detail': 'Seller application approval is required before creating a store.'},
                status=status.HTTP_403_FORBIDDEN,
            )
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


class ShopProductPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response(
            {
                'count': self.page.paginator.count,
                'page': self.page.number,
                'page_size': self.get_page_size(self.request),
                'results': data,
            }
        )

    def get_page_number(self, request, paginator):
        page_number = request.query_params.get(self.page_query_param, 1)
        if page_number in self.last_page_strings:
            return paginator.num_pages
        try:
            page_int = int(page_number)
        except (TypeError, ValueError):
            return 1
        if page_int <= 0:
            return 1
        return page_int


class ShopBannerListAPIView(generics.ListAPIView):
    serializer_class = ShopBannerSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    queryset = ShopBanner.objects.filter(is_active=True).order_by('sort_order', '-id')


class ShopCategoryListAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        rows = list(
            ProductCategory.objects.filter(is_active=True).order_by('sort_order', 'id')
        )
        payload = [{'id': 0, 'name': 'All', 'slug': 'all'}]
        payload.extend(ProductCategorySerializer(rows, many=True).data)
        return Response(payload, status=status.HTTP_200_OK)


class ShopProductListAPIView(generics.ListAPIView):
    serializer_class = ShopProductListSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = ShopProductPagination

    def get_queryset(self):
        queryset = Product.objects.select_related('store', 'category').filter(
            status=Product.STATUS_ACTIVE,
            store__is_active=True,
        ).order_by('-created_at', '-id')
        category = (self.request.query_params.get('category') or '').strip().lower()
        if category and category != 'all':
            queryset = queryset.filter(category__slug=category, category__is_active=True)
        q = (self.request.query_params.get('q') or '').strip()
        if q:
            queryset = queryset.filter(
                Q(title__icontains=q) | Q(description__icontains=q) | Q(slug__icontains=q)
            )
        return queryset


class ShopProductDetailAPIView(generics.RetrieveAPIView):
    serializer_class = ShopProductListSerializer
    permission_classes = [permissions.AllowAny]
    lookup_field = 'id'

    def get_queryset(self):
        return Product.objects.select_related('store', 'category').filter(
            status=Product.STATUS_ACTIVE,
            store__is_active=True,
        )


class SavedProductPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({'count': self.page.paginator.count, 'results': data})


class CartItemListCreateAPIView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = SavedProductPagination
    serializer_class = SavedProductSerializer

    def get_queryset(self):
        return SavedProduct.objects.select_related('product', 'product__store', 'product__category').filter(
            user=self.request.user,
            product__status=Product.STATUS_ACTIVE,
            product__store__is_active=True,
        ).order_by('-created_at', '-id')

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return AddSavedProductSerializer
        return SavedProductSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = SavedProductSerializer(page, many=True, context={'request': request})
        return self.get_paginated_response(serializer.data)

    def create(self, request, *args, **kwargs):
        serializer = AddSavedProductSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        saved, _ = SavedProduct.objects.get_or_create(
            user=request.user,
            product=serializer.validated_data['product'],
        )
        return Response(SavedProductSerializer(saved, context={'request': request}).data, status=status.HTTP_201_CREATED)


class CartItemDeleteAPIView(generics.DestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'
    queryset = SavedProduct.objects.all()

    def get_queryset(self):
        return SavedProduct.objects.filter(user=self.request.user)


class CartCountAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        count = SavedProduct.objects.filter(
            user=request.user,
            product__status=Product.STATUS_ACTIVE,
            product__store__is_active=True,
        ).count()
        return Response({'count': count}, status=status.HTTP_200_OK)


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
        user = getattr(request, 'user', None)
        if not (user and user.is_authenticated):
            return Response({'detail': 'Authentication credentials were not provided.'}, status=status.HTTP_401_UNAUTHORIZED)
        stream = self._stream_for_write(request, pk)
        if stream is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if stream.status == LiveStream.STATUS_ENDED:
            return Response({'detail': 'Live stream has ended.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = LiveChatMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            message = create_live_chat_message(stream=stream, user=user, validated_data=serializer.validated_data, request=request)
        except ValidationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        response_serializer = LiveChatMessageSerializer(message, context={'request': request})
        response_data = response_serializer.data
        try:
            channel_layer = get_channel_layer()
            if channel_layer is not None:
                async_to_sync(channel_layer.group_send)(
                    f'live_chat_{pk}',
                    {
                        'type': 'chat.message',
                        'event': 'message_created',
                        'message': response_data,
                    },
                )
        except Exception:
            logger.exception('live_chat_rest_broadcast_failed stream_id=%s message_id=%s', pk, message.id)
        return Response(response_data, status=status.HTTP_201_CREATED)


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


class LivePaymentMethodManageListCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def _stream(self, request, pk):
        return generics.get_object_or_404(LiveStream, pk=pk, owner=request.user)

    def get(self, request, pk):
        stream = self._stream(request, pk)
        queryset = StreamPaymentMethod.objects.filter(stream=stream).order_by('sort_order', '-created_at', '-id')
        serializer = StreamPaymentMethodSerializer(queryset, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, pk):
        stream = self._stream(request, pk)
        serializer = StreamPaymentMethodSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        payment_method = serializer.save(stream=stream)
        response_serializer = StreamPaymentMethodSerializer(payment_method, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class LivePaymentMethodManageDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def _payment_method(self, request, pk, pm_id):
        return generics.get_object_or_404(
            StreamPaymentMethod,
            pk=pm_id,
            stream_id=pk,
            stream__owner=request.user,
        )

    def patch(self, request, pk, pm_id):
        payment_method = self._payment_method(request, pk, pm_id)
        serializer = StreamPaymentMethodSerializer(
            payment_method,
            data=request.data,
            partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        payment_method = serializer.save()
        response_serializer = StreamPaymentMethodSerializer(payment_method, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, pk, pm_id):
        payment_method = self._payment_method(request, pk, pm_id)
        payment_method.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LivePaymentMethodPublicListAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        stream = generics.get_object_or_404(LiveStream.objects.select_related('owner'), pk=pk)
        if stream.visibility == LiveStream.VISIBILITY_PRIVATE:
            user = getattr(request, 'user', None)
            if not (user and user.is_authenticated and user.id == stream.owner_id):
                return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

        queryset = StreamPaymentMethod.objects.filter(stream=stream, is_active=True).order_by('sort_order', '-created_at', '-id')
        serializer = StreamPaymentMethodSerializer(queryset, many=True, context={'request': request})
        payload = [
            {
                'id': item['id'],
                'method_type': item['method_type'],
                'title': item['title'],
                'qr_image_url': item['qr_image_url'],
                'qr_text': item['qr_text'],
                'wallet_address': item['wallet_address'],
                'sort_order': item['sort_order'],
            }
            for item in serializer.data
        ]
        return Response(payload, status=status.HTTP_200_OK)


class LivePaymentOrderCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def post(self, request, pk):
        stream = generics.get_object_or_404(LiveStream, pk=pk)
        if stream.visibility == LiveStream.VISIBILITY_PRIVATE and stream.owner_id != request.user.id:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = PaymentOrderCreateSerializer(data=request.data, context={'stream': stream})
        serializer.is_valid(raise_exception=True)

        client_request_id = serializer.validated_data.get('client_request_id') or ''
        if client_request_id:
            existing_order = PaymentOrder.objects.filter(
                user=request.user,
                stream=stream,
                client_request_id=client_request_id,
            ).select_related('stream', 'product', 'payment_method', 'paid_by').first()
            if existing_order is not None:
                same_payload = (
                    existing_order.order_type == serializer.validated_data.get('order_type')
                    and existing_order.amount == serializer.validated_data.get('amount')
                    and existing_order.currency == serializer.validated_data.get('currency')
                    and existing_order.product_id == getattr(serializer.validated_data.get('product'), 'id', None)
                    and existing_order.payment_method_id == getattr(serializer.validated_data.get('payment_method'), 'id', None)
                )
                if not same_payload:
                    return Response(
                        {'detail': 'client_request_id was already used with different payload.'},
                        status=status.HTTP_409_CONFLICT,
                    )
                response_serializer = PaymentOrderSerializer(existing_order)
                return Response(response_serializer.data, status=status.HTTP_200_OK)

        order = serializer.save(user=request.user, stream=stream, status=PaymentOrder.STATUS_PENDING)
        response_serializer = PaymentOrderSerializer(order)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class LivePaymentOrderDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk, order_id):
        order = generics.get_object_or_404(
            PaymentOrder.objects.select_related('stream', 'product', 'payment_method', 'user'),
            pk=order_id,
            stream_id=pk,
        )
        can_view = request.user.is_staff or order.user_id == request.user.id or order.stream.owner_id == request.user.id
        if not can_view:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = PaymentOrderSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LivePaymentOrderMarkPaidAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk, order_id):
        order = generics.get_object_or_404(
            PaymentOrder.objects.select_related('stream', 'user', 'product'),
            pk=order_id,
            stream_id=pk,
        )
        if not (request.user.is_staff or order.stream.owner_id == request.user.id):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        paid_note = (request.data.get('note') or '').strip()
        if paid_note and len(paid_note) > 1000:
            return Response({'note': ['Ensure this field has no more than 1000 characters.']}, status=status.HTTP_400_BAD_REQUEST)
        if order.status != PaymentOrder.STATUS_PAID:
            order.status = PaymentOrder.STATUS_PAID
            order.paid_at = timezone.now()
            order.paid_by = request.user
            if paid_note:
                order.paid_note = paid_note
            order.save(update_fields=['status', 'paid_at', 'paid_by', 'paid_note', 'updated_at'])

            chat_room = getattr(order.stream, 'chat_room', None)
            if chat_room and chat_room.is_enabled:
                content = f'Payment received: {order.amount} {order.currency}'
                LiveChatMessage.objects.create(
                    room=chat_room,
                    user=None,
                    message_type=LiveChatMessage.TYPE_PAYMENT,
                    content=content,
                    product=order.product,
                    payment_reference=order.external_reference or str(order.id),
                )
        elif paid_note and not order.paid_note:
            order.paid_note = paid_note
            order.save(update_fields=['paid_note', 'updated_at'])

        serializer = PaymentOrderSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)



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


class CreatorLiveStreamPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100


class CreatorLiveStreamListAPIView(generics.ListAPIView):
    serializer_class = LiveStreamSerializer
    permission_classes = [permissions.IsAuthenticated, IsCreator]
    pagination_class = CreatorLiveStreamPagination

    def get_queryset(self):
        return (
            LiveStream.objects
            .filter(owner=self.request.user)
            .select_related('category', 'owner')
            .order_by('-created_at', '-id')
        )


class LiveStreamCreateAPIView(generics.CreateAPIView):
    serializer_class = LiveStreamSerializer
    permission_classes = [permissions.IsAuthenticated, IsCreator]
    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)



class LiveStreamHealthAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsCreatorOrStaff]

    def get(self, request):
        websocket_url = AntMediaLiveAdapter()._get_websocket_url()
        ant_media_base_url_configured = bool(settings.ANT_MEDIA_BASE_URL)
        websocket_url_configured = bool(websocket_url)
        rest_app_name = settings.ANT_MEDIA_REST_APP_NAME or ''
        app_name = settings.ANT_MEDIA_APP_NAME or ''
        return Response(
            {
                'ant_media_base_url_configured': ant_media_base_url_configured,
                'ant_media_app_name': app_name or None,
                'websocket_url_configured': websocket_url_configured,
                'rest_app_name': rest_app_name or None,
                'udp_ports_note': 'Ensure UDP 50000-60000 are open for WebRTC publishing.',
                'ok': bool(ant_media_base_url_configured and app_name and rest_app_name and websocket_url_configured),
            },
            status=status.HTTP_200_OK,
        )


class LiveStreamQuickStartAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated, IsCreator]
    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        category = None
        category_slug = (request.data.get('category') or '').strip()
        if category_slug:
            category = Category.objects.filter(slug=category_slug, is_active=True).first()
            if category is None:
                return Response({'category': ['Active category not found.']}, status=status.HTTP_400_BAD_REQUEST)

        visibility = (request.data.get('visibility') or LiveStream.VISIBILITY_PUBLIC).strip()
        valid_visibilities = {choice[0] for choice in LiveStream.VISIBILITY_CHOICES}
        if visibility not in valid_visibilities:
            return Response({'visibility': ['Invalid visibility.']}, status=status.HTTP_400_BAD_REQUEST)

        adapter = AntMediaLiveAdapter()
        reusable_statuses = [LiveStream.STATUS_IDLE, LiveStream.STATUS_READY, LiveStream.STATUS_LIVE]
        fresh = request.query_params.get('fresh') == 'true'
        ended_stream_ids = []
        ant_media_stop_warnings = []

        if fresh:
            stale_streams = list(
                LiveStream.objects.filter(
                    owner=request.user,
                    status__in=reusable_statuses,
                )
                .select_related('category', 'owner')
                .order_by('-created_at', '-id')
            )
            now = timezone.now()
            for stale_stream in stale_streams:
                stop_result = adapter.stop_broadcast(stale_stream.stream_key)
                if not stop_result.get('ok'):
                    ant_media_stop_warnings.append(
                        {
                            'live_stream_id': stale_stream.id,
                            'warning': stop_result.get('warning') or 'ant_media_stop_failed',
                            'message': stop_result.get('message'),
                        }
                    )
                stale_stream.status = LiveStream.STATUS_ENDED
                stale_stream.ended_at = now
                stale_stream.ant_media_no_signal_count = 0
                stale_stream.save(update_fields=['status', 'ended_at', 'ant_media_no_signal_count'])
                ended_stream_ids.append(stale_stream.id)
            stream = None
        else:
            stream = (
                LiveStream.objects.filter(
                    owner=request.user,
                    status__in=reusable_statuses,
                )
                .select_related('category', 'owner')
                .order_by('-created_at', '-id')
                .first()
            )
        reused = stream is not None
        if stream is None:
            title = (request.data.get('title') or '').strip() or f"{request.user.display_name}'s Live"
            description = request.data.get('description') or ''
            stream = LiveStream.objects.create(
                owner=request.user,
                title=title,
                description=description,
                visibility=visibility,
                status=LiveStream.STATUS_IDLE,
                category=category,
            )

        ensure_result = adapter.ensure_broadcast(stream)
        if not ensure_result.get('ok'):
            return publish_config_error_response(
                live_payload=self._live_payload(stream, request),
                error=ensure_result.get('error'),
                message=ensure_result.get('message'),
            )

        ant_stream_id = ensure_result.get('stream_id') or stream.stream_key
        if ant_stream_id != stream.stream_key:
            stream.stream_key = ant_stream_id
        now = timezone.now()
        stream.status = LiveStream.STATUS_READY
        stream.publish_started_at = now
        stream.last_publish_signal_at = now
        stream.publish_session_id = secrets.token_hex(16)
        stream.publish_session_expires_at = now + timedelta(minutes=5)
        stream.failure_reason = ''
        stream.save(
            update_fields=[
                'stream_key',
                'status',
                'publish_started_at',
                'last_publish_signal_at',
                'publish_session_id',
                'publish_session_expires_at',
                'failure_reason',
            ]
        )

        publish_config = adapter.get_browser_publish_config(stream)
        if not publish_config.get('ok'):
            return publish_config_error_response(
                live_payload=self._live_payload(stream, request),
                error=publish_config.get('error'),
                message=publish_config.get('message'),
            )

        response_payload = {
            'reused': reused,
            'ant_media_reused': bool(ensure_result.get('reused', False)),
            'live': self._live_payload(stream, request),
            'publish_config': publish_config,
            'publish_session': {
                'id': stream.publish_session_id,
                'stream_id': stream.stream_key,
                'websocket_url': publish_config.get('config', {}).get('websocket_url'),
                'expires_at': stream.publish_session_expires_at,
                'max_start_retry': 20,
            },
            'next_action': 'start_stream',
        }
        if fresh:
            response_payload['fresh'] = True
            response_payload['ended_stream_ids'] = ended_stream_ids
            if ant_media_stop_warnings:
                response_payload['ant_media_stop_warnings'] = ant_media_stop_warnings
        return Response(
            response_payload,
            status=status.HTTP_200_OK if reused else status.HTTP_201_CREATED,
        )

    def _live_payload(self, stream: LiveStream, request) -> dict:
        serializer = LiveStreamSerializer(stream, context={'request': request})
        payload = dict(serializer.data)
        payload['stream_key'] = stream.stream_key
        payload['status'] = stream.status
        return payload


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
        if self._is_owner(request, stream):
            payload['stream_key'] = stream.stream_key
            publish_config = AntMediaLiveAdapter().get_browser_publish_config(stream)
            payload['publish_config'] = publish_config
        return Response(payload, status=status.HTTP_200_OK)

    def _is_owner(self, request, stream: LiveStream) -> bool:
        user = getattr(request, 'user', None)
        return bool(user and user.is_authenticated and stream.owner_id == user.id)


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

    def retrieve(self, request, *args, **kwargs):
        stream = self.get_object()
        self._apply_timeout_compaction(stream)
        stream._normalized_live_fields = AntMediaLiveAdapter().normalize_stream_fields(
            stream,
            persist_no_signal=True,
        )
        normalized = stream._normalized_live_fields
        payload = {
            'id': stream.id,
            'status': stream.status,
            'effective_status': normalized.get('effective_status'),
            'can_start': bool(normalized.get('can_start')),
            'can_end': bool(normalized.get('can_end')),
            'viewer_count': max(normalized.get('viewer_count') or 0, stream.viewer_count or 0),
            'publish': {
                'connected': normalized.get('effective_status') in {'publishing', 'live', LiveStream.STATUS_LIVE},
                'source': 'ant_media' if normalized.get('sync_ok') else 'fallback',
                'last_seen_at': stream.last_publish_signal_at,
                'sync_ok': bool(normalized.get('sync_ok')),
                'sync_error': normalized.get('sync_error'),
            },
            'errors': [stream.failure_reason] if stream.failure_reason else [],
            'live': self.get_serializer(stream).data,
        }
        return Response(payload, status=status.HTTP_200_OK)

    def _apply_timeout_compaction(self, stream):
        now = timezone.now()
        changed = []
        if stream.status == LiveStream.STATUS_READY and stream.publish_started_at and stream.publish_started_at < now - timedelta(minutes=5):
            stream.status = LiveStream.STATUS_FAILED
            stream.failure_reason = 'ready_timeout'
            changed.extend(['status', 'failure_reason'])
        if stream.status == LiveStream.STATUS_READY and stream.publish_session_expires_at and stream.publish_session_expires_at < now:
            stream.status = LiveStream.STATUS_FAILED
            stream.failure_reason = 'session_expired'
            changed.extend(['status', 'failure_reason'])
        if changed:
            stream.save(update_fields=list(set(changed)))


class LiveStreamWatchConfigAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        stream = generics.get_object_or_404(LiveStream.objects.select_related('owner', 'category'), pk=pk)
        user = getattr(request, 'user', None)
        if stream.visibility == LiveStream.VISIBILITY_PRIVATE and not (user and user.is_authenticated and user.id == stream.owner_id):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        if stream.status == LiveStream.STATUS_FAILED:
            return Response({'detail': 'Live stream is failed.'}, status=status.HTTP_409_CONFLICT)

        adapter = AntMediaLiveAdapter()
        normalized = adapter.normalize_stream_fields(stream)
        websocket_url = adapter._get_websocket_url()
        hls_url = adapter._get_playback_url(stream.stream_key)
        if not websocket_url and not hls_url:
            return Response(
                {'detail': 'Playback config unavailable.', 'code': 'playback_config_unavailable'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        self._increment_viewer_count_once(request, stream)
        serializer_data = LiveStreamSerializer(stream, context={'request': request}).data
        normalized_viewer_count = normalized.get('viewer_count') or 0
        viewer_count = max(normalized_viewer_count, stream.viewer_count or 0)
        connected = bool(stream.status == LiveStream.STATUS_LIVE and normalized.get('effective_status') in {'live', 'publishing'})
        playback_mode = 'webrtc' if websocket_url else 'hls'
        payload = {
            'live_id': stream.id,
            'status': stream.status,
            'effective_status': normalized.get('effective_status'),
            'viewer_count': viewer_count,
            'playback': {
                'mode': playback_mode,
                'stream_id': stream.stream_key,
                'websocket_url': websocket_url,
                'hls_url': hls_url,
                'connected': connected,
            },
            'fallback': {
                'mode': 'hls',
                'hls_url': hls_url,
            },
            'thumbnail_url': serializer_data.get('thumbnail_url'),
            'preview_image_url': serializer_data.get('preview_image_url'),
            'snapshot_url': serializer_data.get('snapshot_url'),
        }
        return Response(payload, status=status.HTTP_200_OK)

    def _increment_viewer_count_once(self, request, stream):
        user = getattr(request, 'user', None)
        if stream.status in {LiveStream.STATUS_ENDED, LiveStream.STATUS_FAILED}:
            return
        if user and user.is_authenticated and user.id == stream.owner_id:
            return

        cache_key = self._viewer_count_cache_key(request, stream)
        if not cache.add(cache_key, True, timeout=60):
            return
        LiveStream.objects.filter(pk=stream.pk).update(viewer_count=F('viewer_count') + 1)
        stream.refresh_from_db(fields=['viewer_count'])

    def _viewer_count_cache_key(self, request, stream):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            viewer_id = f'user:{user.id}'
        else:
            forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
            ip_address = forwarded_for.split(',')[0].strip() or request.META.get('REMOTE_ADDR', '')
            user_agent = request.META.get('HTTP_USER_AGENT', '')
            fingerprint = hashlib.sha256(f'{ip_address}|{user_agent}'.encode('utf-8')).hexdigest()
            viewer_id = f'anon:{fingerprint}'
        return f'live:{stream.pk}:watch-config-viewer:{viewer_id}'


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
        stream = generics.get_object_or_404(LiveStream.objects.select_related('category', 'owner'), pk=pk)
        if stream.owner_id != request.user.id:
            return live_owner_forbidden_response()
        now = timezone.now()
        adapter = AntMediaLiveAdapter()

        if self.new_status == LiveStream.STATUS_LIVE:
            if stream.status == LiveStream.STATUS_LIVE:
                live_payload = LiveStreamSerializer(stream, context={'request': request}).data
                return Response(
                    {'ok': True, 'status': LiveStream.STATUS_LIVE, 'already_started': True, 'live': live_payload},
                    status=status.HTTP_200_OK,
                )
            if stream.status == LiveStream.STATUS_ENDED:
                return Response({'detail': 'Ended stream cannot be started again.'}, status=status.HTTP_409_CONFLICT)
            if stream.status == LiveStream.STATUS_FAILED:
                return Response({'detail': 'Failed stream cannot be started. Please create a new session.'}, status=status.HTTP_409_CONFLICT)
            if stream.status not in [LiveStream.STATUS_IDLE, LiveStream.STATUS_READY]:
                return Response(
                    {'detail': 'Only idle or ready streams can be started.'},
                    status=status.HTTP_409_CONFLICT,
                )
            session_id = (request.data.get('publish_session_id') or '').strip()
            if stream.publish_session_id and session_id and session_id != stream.publish_session_id:
                return Response({'detail': 'stream/session mismatch'}, status=status.HTTP_409_CONFLICT)
            if stream.publish_session_expires_at and stream.publish_session_expires_at < now:
                stream.status = LiveStream.STATUS_FAILED
                stream.failure_reason = 'session_expired'
                stream.save(update_fields=['status', 'failure_reason'])
                return Response({'detail': 'session expired'}, status=status.HTTP_409_CONFLICT)
            skip_ant_media = request.query_params.get('skip_ant_media') == 'true'
            bypass_enabled = settings.DEBUG or getattr(settings, 'ALLOW_LIVE_START_BYPASS', False)
            if skip_ant_media and not bypass_enabled:
                return Response(
                    {'detail': 'Live start bypass is not enabled.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if not skip_ant_media:
                sync = adapter.get_broadcast_status(stream.stream_key)
                ant_status = sync.get('ant_media_status')
                if ant_status != 'broadcasting':
                    return Response(
                        {
                            'detail': 'Stream is not publishing yet.',
                            'status': 'waiting_for_signal',
                            'django_status': stream.status,
                            'ant_media_status': ant_status,
                            'effective_status': 'waiting_for_signal',
                            'next_action': 'retry_status',
                            'sync_ok': sync.get('sync_ok', False),
                            'sync_error': sync.get('sync_error'),
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
            stream.status = LiveStream.STATUS_LIVE
            stream.started_at = now
            stream.ended_at = None
            stream.ant_media_no_signal_count = 0
            stream.last_publish_signal_at = now
            stream.failure_reason = ''
            stream.thumbnail_capture_status = LiveStream.THUMBNAIL_CAPTURE_PENDING
            stream.thumbnail_capture_error = ''
            stream.save(update_fields=['status', 'started_at', 'ended_at', 'ant_media_no_signal_count', 'last_publish_signal_at', 'failure_reason', 'thumbnail_capture_status', 'thumbnail_capture_error'])
            self._trigger_async_snapshot(stream.id)
        elif self.new_status == LiveStream.STATUS_ENDED:
            if stream.status == LiveStream.STATUS_ENDED:
                return Response(
                    {'detail': 'Only non-ended streams can be ended.'},
                    status=status.HTTP_409_CONFLICT,
                )
            stream.status = LiveStream.STATUS_ENDED
            stream.ended_at = now
            stream.ant_media_no_signal_count = 0
            stream.save(update_fields=['status', 'ended_at', 'ant_media_no_signal_count'])
            stop_result = adapter.stop_broadcast(stream.stream_key)
            stream._ant_media_stop_result = stop_result

        serializer = LiveStreamSerializer(stream, context={'request': request})
        payload = dict(serializer.data)
        stop_result = getattr(stream, '_ant_media_stop_result', None)
        if stop_result and not stop_result.get('ok'):
            payload['warning'] = stop_result.get('warning') or 'ant_media_stop_failed'
            payload['warning_detail'] = stop_result.get('message')
        return Response(payload, status=status.HTTP_200_OK)

    def _trigger_async_snapshot(self, stream_id: int):
        def _runner():
            try:
                stream = LiveStream.objects.get(pk=stream_id)
                capture_live_snapshot(stream, seek_seconds=5)
            except Exception:
                logger.exception('live snapshot capture failed stream_id=%s', stream_id)

        threading.Thread(target=_runner, daemon=True).start()


class LiveStreamPrepareAPIView(APIView):
    """Prepare a live stream and return the backend-owned publish stream id.

    Contract: the frontend should publish to Ant Media using the stream id from
    this response (`stream_key` and `publish_session.ant_media.stream_id`).
    """
    permission_classes = [permissions.IsAuthenticated, IsCreator]

    def post(self, request, pk):
        stream = generics.get_object_or_404(
            LiveStream.objects.select_related('category', 'owner'),
            pk=pk,
        )
        if stream.owner_id != request.user.id:
            return live_owner_forbidden_response()
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
            return publish_config_error_response(
                live_payload=self._live_payload(stream, request),
                error=ensure_result.get('error'),
                message=ensure_result.get('message'),
            )

        ant_stream_id = ensure_result.get('stream_id') or stream.stream_key
        if ant_stream_id != stream.stream_key:
            stream.stream_key = ant_stream_id
            stream.save(update_fields=['stream_key'])
        logger.debug('live_prepare persisted stream_id live_id=%s stream_id=%s', stream.id, stream.stream_key)

        publish_config = adapter.get_browser_publish_config(stream)
        if not publish_config.get('ok'):
            return publish_config_error_response(
                live_payload=self._live_payload(stream, request),
                error=publish_config.get('error'),
                message=publish_config.get('message'),
            )
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

    def _live_payload(self, stream: LiveStream, request) -> dict:
        serializer = LiveStreamSerializer(stream, context={'request': request})
        payload = dict(serializer.data)
        payload['stream_key'] = stream.stream_key
        payload['status'] = stream.status
        return payload


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
        access_type = self.request.query_params.get('access_type')
        search = self.request.query_params.get('search')
        ordering = self.request.query_params.get('ordering')

        category = LEGACY_CATEGORY_SLUG_ALIASES.get(category, category)
        if category:
            queryset = queryset.filter(category__slug=category)
        if access_type:
            queryset = queryset.filter(access_type=access_type)
        if search:
            queryset = queryset.filter(Q(title__icontains=search))
        if ordering in {'created_at', '-created_at'}:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by('-created_at', '-id')
        return queryset


class CreatorVideoListCreateAPIView(VideoListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated, IsCreator]


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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['mask_locked_file_fields'] = True
        return context

    def get_queryset(self):
        queryset = annotate_videos_for_request(
            Video.objects.filter(
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ),
            self.request,
        )
        category = self.request.query_params.get('category')
        access_type = self.request.query_params.get('access_type')
        search = self.request.query_params.get('search')
        ordering = self.request.query_params.get('ordering')

        category = LEGACY_CATEGORY_SLUG_ALIASES.get(category, category)
        if category:
            queryset = queryset.filter(category__slug=category)
        if access_type:
            queryset = queryset.filter(access_type=access_type)
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

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['mask_locked_file_fields'] = True
        return context

    def get_queryset(self):
        return annotate_videos_for_request(
            Video.objects.filter(
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ),
            self.request,
        )


class PublicRelatedVideoListAPIView(generics.ListAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['mask_locked_file_fields'] = True
        return context

    def get_queryset(self):
        current_video = generics.get_object_or_404(
            Video.objects.select_related('category').filter(
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ),
            pk=self.kwargs['pk'],
        )
        limit = self.request.query_params.get('limit', 8)

        try:
            limit = max(1, min(int(limit), 20))
        except (TypeError, ValueError):
            limit = 8

        queryset = annotate_videos_for_request(
            Video.objects.filter(
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ).exclude(pk=current_video.pk),
            self.request,
        )
        if current_video.category_id:
            queryset = queryset.filter(category=current_video.category_id)
        return queryset.order_by('-created_at', '-id')[:limit]


class VideoRecommendationsAPIView(generics.ListAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['mask_locked_file_fields'] = True
        return context

    def get_queryset(self):
        current_video = generics.get_object_or_404(
            Video.objects.select_related('category', 'owner').filter(
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ),
            pk=self.kwargs['pk'],
        )

        try:
            limit = int(self.request.query_params.get('limit', 10) or 10)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(limit, 30))

        exclude_ids = {current_video.pk}
        raw_exclude_ids = self.request.query_params.get('exclude_ids', '')
        for raw in raw_exclude_ids.split(','):
            raw = raw.strip()
            if not raw:
                continue
            try:
                exclude_ids.add(int(raw))
            except (TypeError, ValueError):
                continue

        base = annotate_videos_for_request(
            Video.objects.filter(
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ),
            self.request,
        )

        ordered_ids = []

        def append_ids(qs, remaining):
            if remaining <= 0:
                return
            ids = list(
                qs.exclude(id__in=exclude_ids)
                .order_by('-created_at', '-id')
                .values_list('id', flat=True)[:remaining]
            )
            ordered_ids.extend(ids)
            exclude_ids.update(ids)

        if current_video.category_id:
            append_ids(base.filter(category_id=current_video.category_id), limit - len(ordered_ids))

        append_ids(base.filter(owner_id=current_video.owner_id), limit - len(ordered_ids))

        append_ids(base, limit - len(ordered_ids))

        if not ordered_ids:
            return base.none()

        ordering = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(ordered_ids)], output_field=IntegerField())
        return base.filter(pk__in=ordered_ids).order_by(ordering)


class PublicVideoInteractionSummaryAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, pk):
        video = generics.get_object_or_404(
            annotate_videos_for_request(
                Video.objects.filter(
                    visibility=Video.VISIBILITY_PUBLIC,
                    status=Video.STATUS_ACTIVE,
                ),
                request,
            ).filter(status=Video.STATUS_ACTIVE),
            pk=pk,
        )
        serializer = VideoInteractionSummarySerializer(video, context={'request': request})
        return Response(serializer.data)


class PublicVideoShareTrackAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, pk):
        video = generics.get_object_or_404(
            Video.objects.filter(
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ),
            pk=pk,
        )
        channel = (request.data.get('channel') or '').strip()[:64]
        user = request.user if request.user.is_authenticated else None
        VideoShare.objects.create(
            user=user,
            video=video,
            channel=channel,
            ip_address=get_client_ip(request),
            user_agent=(request.META.get('HTTP_USER_AGENT') or '')[:1000],
        )
        Video.objects.filter(pk=video.pk).update(share_count=F('share_count') + 1)
        video.refresh_from_db(fields=['share_count'])
        return Response(
            {
                'video_id': video.id,
                'share_count': video.share_count,
                'channel': channel,
            },
            status=status.HTTP_200_OK,
        )


class PublicVideoGiftSendAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        video = generics.get_object_or_404(
            Video.objects.select_related('owner').filter(
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ),
            pk=pk,
        )

        if 'amount' in request.data:
            serializer = ContentGiftSendSerializer(data=request.data or {})
            serializer.is_valid(raise_exception=True)
            amount = serializer.validated_data['amount']
            payment_method = serializer.validated_data['payment_method']
            try:
                tx, sender_balance, receiver_balance = GiftService.send_content_gift(
                    sender=request.user,
                    receiver=video.owner,
                    target_type=GiftTransaction.TARGET_VIDEO,
                    target_id=video.id,
                    video=video,
                    amount=amount,
                    payment_method=payment_method,
                )
            except ValidationError as exc:
                error_text = str(exc)
                if 'Insufficient Meow Points balance.' in error_text or 'Insufficient Meow Credit balance.' in error_text:
                    return Response(
                        {
                            'code': 'insufficient_balance',
                            'detail': 'Insufficient balance.',
                            'payment_method': payment_method,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                return Response({'detail': error_text}, status=status.HTTP_400_BAD_REQUEST)

            response_serializer = ContentGiftSendResponseSerializer(
                {
                    'video_id': video.id,
                    'receiver_id': video.owner_id,
                    'amount': amount,
                    'payment_method': payment_method,
                    'points_charged': tx.points_amount,
                    'credits_charged': tx.credits_amount,
                    'sender_balance': sender_balance,
                    'receiver_balance': receiver_balance,
                    'gift_transaction_id': tx.id,
                }
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        serializer = GiftSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data.get('gift_id'):
            gift = generics.get_object_or_404(Gift, pk=serializer.validated_data['gift_id'])
        else:
            gift = generics.get_object_or_404(Gift, code=serializer.validated_data['gift_code'])
        cutoff = timezone.now() - timedelta(seconds=2)
        existing_tx = (
            GiftTransaction.objects.filter(
                sender=request.user,
                video=video,
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
            tx = GiftService.send_video_gift(
                sender=request.user,
                receiver=video.owner,
                video=video,
                gift=gift,
                quantity=serializer.validated_data['quantity'],
            )
        except ValidationError as exc:
            error_text = str(exc)
            if 'Insufficient Meow Points balance.' in error_text:
                return Response(
                    {
                        'code': 'insufficient_balance',
                        'detail': 'Insufficient balance.',
                        'payment_method': GiftTransaction.PAYMENT_MEOW_POINTS,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if 'Gift is not active.' in error_text:
                return Response({'detail': 'Gift is not active.'}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'detail': error_text}, status=status.HTTP_400_BAD_REQUEST)

        response_serializer = GiftTransactionSerializer(tx)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

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

        subscriber_count = follow_user(request.user, channel)
        return Response(
            {
                'channel_id': channel.pk,
                'subscriber_count': subscriber_count,
                'follower_count': subscriber_count,
                'is_following': True,
                'viewer_is_following': True,
                'is_subscribed': True,
                'viewer_is_subscribed': True,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        channel = generics.get_object_or_404(User, pk=pk)
        subscriber_count = unfollow_user(request.user, channel)
        return Response(
            {
                'channel_id': channel.pk,
                'subscriber_count': subscriber_count,
                'follower_count': subscriber_count,
                'is_following': False,
                'viewer_is_following': False,
                'is_subscribed': False,
                'viewer_is_subscribed': False,
            },
            status=status.HTTP_200_OK,
        )


class CreatorFollowAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, creator_id):
        creator = generics.get_object_or_404(User, pk=creator_id)
        validation_response = self._validate_creator_target(request, creator)
        if validation_response is not None:
            return validation_response

        subscriber_count = follow_user(request.user, creator)
        return Response(
            self._response_payload(creator=creator, is_following=True, subscriber_count=subscriber_count),
            status=status.HTTP_200_OK,
        )

    def delete(self, request, creator_id):
        creator = generics.get_object_or_404(User, pk=creator_id)
        validation_response = self._validate_creator_target(request, creator)
        if validation_response is not None:
            return validation_response

        subscriber_count = unfollow_user(request.user, creator)
        return Response(
            self._response_payload(creator=creator, is_following=False, subscriber_count=subscriber_count),
            status=status.HTTP_200_OK,
        )

    def _validate_creator_target(self, request, creator):
        if creator.pk == request.user.pk:
            return Response({'detail': 'You cannot follow yourself.'}, status=status.HTTP_400_BAD_REQUEST)
        if not creator.is_creator:
            return Response({'detail': 'Target user is not a creator.'}, status=status.HTTP_400_BAD_REQUEST)
        return None

    def _response_payload(self, *, creator, is_following: bool, subscriber_count: int) -> dict:
        return {
            'creator_id': creator.pk,
            'is_following': is_following,
            'subscriber_count': subscriber_count,
            # Backward-compatible aliases for existing clients.
            'viewer_is_following': is_following,
            'follower_count': subscriber_count,
            'is_subscribed': is_following,
            'viewer_is_subscribed': is_following,
        }


class PublicCreatorDetailAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, creator_id):
        creator = generics.get_object_or_404(User.objects.filter(is_creator=True), pk=creator_id)
        serializer = PublicCreatorSerializer(creator, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class PublicUserDetailAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, user_id):
        user = generics.get_object_or_404(User, pk=user_id)
        serializer = PublicUserProfileSerializer(user, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class PublicUserFollowAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, user_id):
        user = generics.get_object_or_404(User, pk=user_id)
        validation_response = self._validate_target(request, user)
        if validation_response is not None:
            return validation_response
        follower_count = follow_user(request.user, user)
        return Response(self._response_payload(user, True, follower_count), status=status.HTTP_200_OK)

    def delete(self, request, user_id):
        user = generics.get_object_or_404(User, pk=user_id)
        validation_response = self._validate_target(request, user)
        if validation_response is not None:
            return validation_response
        follower_count = unfollow_user(request.user, user)
        return Response(self._response_payload(user, False, follower_count), status=status.HTTP_200_OK)

    def _validate_target(self, request, user):
        if user.pk == request.user.pk:
            return Response({'detail': 'You cannot follow yourself.'}, status=status.HTTP_400_BAD_REQUEST)
        return None

    def _response_payload(self, user, is_following, follower_count):
        return {
            'user_id': user.pk,
            'is_following': is_following,
            'viewer_is_following': is_following,
            'follower_count': follower_count,
            'subscriber_count': follower_count,
            'is_subscribed': is_following,
            'viewer_is_subscribed': is_following,
        }


class PublicUserFollowersListAPIView(generics.ListAPIView):
    serializer_class = PublicUserListItemSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = VideoPagination

    def get_queryset(self):
        user = generics.get_object_or_404(User, pk=self.kwargs['user_id'])
        return User.objects.filter(
            channel_subscriptions__channel=user,
        ).order_by('-channel_subscriptions__created_at', '-channel_subscriptions__id')


class PublicUserFollowingListAPIView(generics.ListAPIView):
    serializer_class = PublicUserListItemSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = VideoPagination

    def get_queryset(self):
        user = generics.get_object_or_404(User, pk=self.kwargs['user_id'])
        return User.objects.filter(
            subscriptions_received__subscriber=user,
        ).order_by('-subscriptions_received__created_at', '-subscriptions_received__id')


class PublicCreatorVideoListAPIView(generics.ListAPIView):
    serializer_class = VideoSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = VideoPagination

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['mask_locked_file_fields'] = True
        return context

    def get_queryset(self):
        creator = generics.get_object_or_404(User.objects.filter(is_creator=True), pk=self.kwargs['creator_id'])
        queryset = annotate_videos_for_request(
            Video.objects.filter(
                owner=creator,
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ),
            self.request,
        )

        category = self.request.query_params.get('category')
        access_type = self.request.query_params.get('access_type')
        search = self.request.query_params.get('search')
        ordering = self.request.query_params.get('ordering')

        category = LEGACY_CATEGORY_SLUG_ALIASES.get(category, category)
        if category:
            queryset = queryset.filter(category__slug=category)
        if access_type:
            queryset = queryset.filter(access_type=access_type)
        if search:
            queryset = queryset.filter(Q(title__icontains=search))
        if ordering in {'created_at', '-created_at'}:
            queryset = queryset.order_by(ordering)
        else:
            queryset = queryset.order_by('-created_at', '-id')
        return queryset


class PublicCreatorDramaListAPIView(generics.ListAPIView):
    serializer_class = DramaSeriesSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = VideoPagination

    def get_queryset(self):
        creator = generics.get_object_or_404(User.objects.filter(is_creator=True), pk=self.kwargs['creator_id'])
        return (
            DramaSeries.objects
            .select_related('owner')
            .filter(
                owner=creator,
                is_active=True,
                status=DramaSeries.STATUS_PUBLISHED,
            )
            .order_by('-created_at', '-id')
        )


class PublicCreatorLiveListAPIView(generics.ListAPIView):
    serializer_class = LiveStreamSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = VideoPagination

    def get_queryset(self):
        creator = generics.get_object_or_404(User.objects.filter(is_creator=True), pk=self.kwargs['creator_id'])
        return (
            LiveStream.objects
            .select_related('owner', 'category')
            .filter(owner=creator)
            .exclude(visibility=LiveStream.VISIBILITY_PRIVATE)
            .annotate(
                status_priority=Case(
                    When(status=LiveStream.STATUS_LIVE, then=Value(0)),
                    When(status=LiveStream.STATUS_ENDED, then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                )
            )
            .order_by('status_priority', '-created_at', '-id')
        )


class BillingPlanListAPIView(generics.ListAPIView):
    serializer_class = BillingPlanSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        return BillingPlan.objects.filter(is_active=True).order_by('price_amount', 'id')


class BillingSubscriptionCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        serializer = BillingSubscriptionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.validated_data['plan']
        subscription = BillingSubscription.objects.create(
            user=request.user,
            plan=plan,
            status=BillingSubscription.STATUS_ACTIVE,
            auto_renew=True,
        )
        response_serializer = BillingSubscriptionSerializer(subscription)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class BillingMySubscriptionAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        subscription = BillingSubscription.objects.filter(
            user=request.user,
            status=BillingSubscription.STATUS_ACTIVE,
        ).select_related('plan').first()
        if subscription is None:
            return Response(None, status=status.HTTP_200_OK)
        serializer = BillingSubscriptionSerializer(subscription)
        return Response(serializer.data, status=status.HTTP_200_OK)


class BillingSubscriptionCancelAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        subscription = generics.get_object_or_404(
            BillingSubscription.objects.select_related('plan'),
            pk=pk,
            user=request.user,
        )
        if subscription.status == BillingSubscription.STATUS_ACTIVE:
            subscription.status = BillingSubscription.STATUS_CANCELLED
            subscription.auto_renew = False
            subscription.cancelled_at = timezone.now()
            subscription.save(update_fields=['status', 'auto_renew', 'cancelled_at', 'updated_at'])
        serializer = BillingSubscriptionSerializer(subscription)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MembershipPlanListAPIView(generics.ListAPIView):
    serializer_class = MembershipPlanSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        return MembershipPlan.objects.filter(is_active=True).order_by('sort_order', 'id')


class ManualMembershipPaymentInfoAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        payment_asset = (request.query_params.get('payment_asset') or PaymentOrder.PAYMENT_ASSET_THB_LTT).strip()
        if payment_asset != PaymentOrder.PAYMENT_ASSET_THB_LTT:
            return Response({'detail': 'manual flow only supports thb_ltt.'}, status=status.HTTP_400_BAD_REQUEST)
        plan_code = (request.query_params.get('plan_code') or '').strip()
        if not plan_code:
            return Response({'plan_code': ['This query parameter is required.']}, status=status.HTTP_400_BAD_REQUEST)

        plan = generics.get_object_or_404(
            MembershipPlan.objects.filter(is_active=True),
            code=plan_code,
        )
        pay_to_address = (settings.LBRY_PLATFORM_RECEIVE_ADDRESS or '').strip()
        if not pay_to_address:
            return Response({'detail': 'Manual membership payment address is not configured.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        purchase_preview = build_membership_purchase_preview(request.user, plan)
        currency = TOKEN_SYMBOL
        notice = (
            f'Send the exact {currency} amount to the platform address, '
            'then wait for staff verification. '
            'This endpoint does not create an order or accept txid submission.'
        )
        return Response(
            {
                'plan_code': plan.code,
                'plan_name': plan.name,
                'expected_amount_lbc': f'{plan.price_lbc:.8f}',
                'currency': currency,
                'pay_to_address': pay_to_address,
                'required_confirmations': int(settings.LBC_MIN_CONFIRMATIONS),
                'notice': notice,
                **purchase_preview,
            },
            status=status.HTTP_200_OK,
        )


class ManualMembershipTxHintListAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def get(self, request):
        payments = list(
            ManualMembershipPayment.objects.filter(user=request.user)
            .select_related('plan')
            .order_by('-created_at', '-id')[:50]
        )
        serializer = ManualMembershipPaymentHintSerializer(payments, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        payment_asset = (request.data.get('payment_asset') or PaymentOrder.PAYMENT_ASSET_THB_LTT).strip()
        if payment_asset != PaymentOrder.PAYMENT_ASSET_THB_LTT:
            return Response({'detail': 'manual tx-hint only supports thb_ltt.'}, status=status.HTTP_400_BAD_REQUEST)
        serializer = ManualMembershipTxHintSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = generics.get_object_or_404(
            MembershipPlan.objects.filter(is_active=True),
            code=serializer.validated_data['plan_code'],
        )
        txid = serializer.validated_data['txid']
        existing_txid_payment = ManualMembershipPayment.objects.select_related('payment_order').filter(txid=txid).first()
        if existing_txid_payment is not None:
            return Response(
                self._duplicate_txid_payload(existing_txid_payment),
                status=status.HTTP_409_CONFLICT,
            )

        blocking_payment = (
            ManualMembershipPayment.objects.filter(
                user=request.user,
                plan=plan,
                status__in=[
                    ManualMembershipPayment.STATUS_PENDING,
                    ManualMembershipPayment.STATUS_SUBMITTED,
                    ManualMembershipPayment.STATUS_PENDING_CONFIRMATION,
                    ManualMembershipPayment.STATUS_DRY_RUN_VERIFIED,
                ],
            )
            .order_by('-created_at', '-id')
            .first()
        )
        if blocking_payment is not None:
            return Response(
                {
                    'detail': 'A pending manual membership payment already exists.',
                    'manual_payment_id': blocking_payment.id,
                    'status': blocking_payment.status,
                },
                status=status.HTTP_409_CONFLICT,
            )

        purchase_preview = build_membership_purchase_preview(request.user, plan)
        verification = ManualMembershipChainVerifier().verify(txid=txid, plan=plan)
        payment_status = self._status_from_verification(verification)
        reject_reason = verification['reason'] if payment_status == ManualMembershipPayment.STATUS_REJECTED else ''
        try:
            with transaction.atomic():
                payment = ManualMembershipPayment.objects.create(
                    user=request.user,
                    plan=plan,
                    txid=txid,
                    expected_amount_lbc=verification['expected_amount_lbc'],
                    actual_amount_lbc=verification['actual_amount_lbc'],
                    pay_to_address=verification['pay_to_address'],
                    confirmations=verification['confirmations'],
                    status=payment_status,
                    reject_reason=reject_reason,
                    raw_tx=verification['raw_tx'],
                    verified_at=timezone.now() if verification['ok'] else None,
                )
                if verification['ok'] and bool(getattr(settings, 'MANUAL_MEMBERSHIP_AUTO_ACTIVATE', False)):
                    payment_order, membership = self._activate_verified_manual_payment(
                        payment=payment,
                        user=request.user,
                        plan=plan,
                        verification=verification,
                    )
                    payment.payment_order = payment_order
                    payment.membership = membership
                    payment.status = ManualMembershipPayment.STATUS_VERIFIED
                    payment.verified_at = timezone.now()
                    payment.save(update_fields=['payment_order', 'membership', 'status', 'verified_at', 'updated_at'])
        except IntegrityError:
            existing_payment = ManualMembershipPayment.objects.select_related('payment_order').filter(txid=txid).first()
            if existing_payment is not None:
                return Response(
                    self._duplicate_txid_payload(existing_payment),
                    status=status.HTTP_409_CONFLICT,
                )
            raise

        return Response(
            self._manual_payment_response_payload(
                payment=payment,
                verification=verification,
                purchase_preview=purchase_preview,
            ),
            status=status.HTTP_201_CREATED,
        )

    def _status_from_verification(self, verification: dict) -> str:
        if verification['ok']:
            if bool(getattr(settings, 'MANUAL_MEMBERSHIP_AUTO_ACTIVATE', False)):
                return ManualMembershipPayment.STATUS_SUBMITTED
            return ManualMembershipPayment.STATUS_DRY_RUN_VERIFIED
        if verification['reason'] == 'pending_confirmation':
            return ManualMembershipPayment.STATUS_PENDING_CONFIRMATION
        if verification['reason'] == 'chain_lookup_failed':
            return ManualMembershipPayment.STATUS_FAILED
        return ManualMembershipPayment.STATUS_REJECTED

    def _serialize_verification(self, verification: dict) -> dict:
        payload = dict(verification)
        payload['expected_amount_lbc'] = f"{verification['expected_amount_lbc']:.8f}"
        payload['actual_amount_lbc'] = f"{verification['actual_amount_lbc']:.8f}"
        return payload

    def _manual_payment_response_payload(
        self,
        *,
        payment: ManualMembershipPayment,
        verification: dict | None = None,
        purchase_preview: dict | None = None,
    ) -> dict:
        payment_order = payment.payment_order if payment.payment_order_id else None
        payload = {
            'verified': payment.status == ManualMembershipPayment.STATUS_VERIFIED
            or payment.status == ManualMembershipPayment.STATUS_DRY_RUN_VERIFIED,
            'manual_payment_id': payment.id,
            'status': payment.status,
            'order_no': payment_order.order_no if payment_order is not None else '',
            'payment': ManualMembershipPaymentHintSerializer(payment).data,
            'payment_order': MembershipOrderSerializer(payment_order).data if payment_order is not None else None,
            'membership': MyMembershipSerializer.from_membership(payment.membership).data if payment.membership_id else None,
        }
        if purchase_preview is not None:
            payload.update(purchase_preview)
        if verification is not None:
            payload['verification'] = self._serialize_verification(verification)
        return payload

    def _duplicate_txid_payload(self, payment: ManualMembershipPayment) -> dict:
        payment_order = payment.payment_order if payment.payment_order_id else None
        return {
            'detail': 'txid already submitted.',
            'manual_payment_id': payment.id,
            'status': payment.status,
            'order_no': payment_order.order_no if payment_order is not None else '',
            'created_at': payment.created_at,
            'verified_at': payment.verified_at,
        }

    def _activate_verified_manual_payment(self, *, payment: ManualMembershipPayment, user, plan: MembershipPlan, verification: dict):
        actual_amount = verification['actual_amount_lbc']
        expected_amount = verification['expected_amount_lbc']
        order_status = PaymentOrder.STATUS_OVERPAID if actual_amount > expected_amount else PaymentOrder.STATUS_PAID
        now = timezone.now()
        payment_order = PaymentOrder.objects.create(
            user=user,
            order_type=PaymentOrder.TYPE_MEMBERSHIP,
            target_type='membership_plan',
            target_id=plan.id,
            plan_code_snapshot=plan.code,
            plan_name_snapshot=plan.name,
            expected_amount_lbc=expected_amount,
            actual_amount_lbc=actual_amount,
            txid=verification['txid'],
            confirmations=verification['confirmations'],
            pay_to_address=verification['pay_to_address'],
            status=order_status,
            paid_at=now,
            order_no=self._generate_manual_order_no(),
            amount='0.00',
            currency=TOKEN_SYMBOL,
        )
        membership = MembershipActivationService().activate_for_order(order=payment_order)
        return payment_order, membership

    def _generate_manual_order_no(self) -> str:
        for _ in range(8):
            candidate = f'MO{timezone.now():%Y%m%d}{secrets.token_hex(4).upper()}'
            if not PaymentOrder.objects.filter(order_no=candidate).exists():
                return candidate
        raise LbryDaemonError('Unable to generate unique membership order number.')



class ManualMembershipTxHintVerifyNowAPIView(ManualMembershipTxHintListAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        with transaction.atomic():
            payment = generics.get_object_or_404(
                ManualMembershipPayment.objects.select_for_update().select_related('plan', 'payment_order', 'membership'),
                pk=pk,
                user=request.user,
            )
            if payment.status == ManualMembershipPayment.STATUS_VERIFIED:
                return Response(
                    self._manual_payment_response_payload(payment=payment),
                    status=status.HTTP_200_OK,
                )
            if payment.status != ManualMembershipPayment.STATUS_PENDING_CONFIRMATION:
                return Response(
                    {
                        **self._manual_payment_response_payload(payment=payment),
                        'detail': 'Manual membership payment is not pending confirmation.',
                        'reason': 'not_pending_confirmation',
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            verification = ManualMembershipChainVerifier().verify(txid=payment.txid, plan=payment.plan)
            payment.expected_amount_lbc = verification['expected_amount_lbc']
            payment.actual_amount_lbc = verification['actual_amount_lbc']
            payment.pay_to_address = verification['pay_to_address']
            payment.confirmations = verification['confirmations']
            payment.raw_tx = verification['raw_tx']

            if verification['ok']:
                if bool(getattr(settings, 'MANUAL_MEMBERSHIP_AUTO_ACTIVATE', False)):
                    payment_order, membership = self._activate_verified_manual_payment(
                        payment=payment,
                        user=request.user,
                        plan=payment.plan,
                        verification=verification,
                    )
                    payment.payment_order = payment_order
                    payment.membership = membership
                    payment.status = ManualMembershipPayment.STATUS_VERIFIED
                    payment.reject_reason = ''
                    payment.verified_at = timezone.now()
                    payment.save(
                        update_fields=[
                            'expected_amount_lbc',
                            'actual_amount_lbc',
                            'pay_to_address',
                            'confirmations',
                            'raw_tx',
                            'payment_order',
                            'membership',
                            'status',
                            'reject_reason',
                            'verified_at',
                            'updated_at',
                        ]
                    )
                else:
                    payment.status = ManualMembershipPayment.STATUS_DRY_RUN_VERIFIED
                    payment.reject_reason = ''
                    payment.verified_at = timezone.now()
                    payment.save(
                        update_fields=[
                            'expected_amount_lbc',
                            'actual_amount_lbc',
                            'pay_to_address',
                            'confirmations',
                            'raw_tx',
                            'status',
                            'reject_reason',
                            'verified_at',
                            'updated_at',
                        ]
                    )
            elif verification['reason'] == 'pending_confirmation':
                payment.status = ManualMembershipPayment.STATUS_PENDING_CONFIRMATION
                payment.reject_reason = ''
                payment.save(
                    update_fields=[
                        'expected_amount_lbc',
                        'actual_amount_lbc',
                        'pay_to_address',
                        'confirmations',
                        'raw_tx',
                        'status',
                        'reject_reason',
                        'updated_at',
                    ]
                )
            else:
                payment.status = (
                    ManualMembershipPayment.STATUS_FAILED
                    if verification['reason'] == 'chain_lookup_failed'
                    else ManualMembershipPayment.STATUS_REJECTED
                )
                payment.reject_reason = verification['reason']
                payment.save(
                    update_fields=[
                        'expected_amount_lbc',
                        'actual_amount_lbc',
                        'pay_to_address',
                        'confirmations',
                        'raw_tx',
                        'status',
                        'reject_reason',
                        'updated_at',
                    ]
                )

            payment.refresh_from_db()
            return Response(
                self._manual_payment_response_payload(payment=payment, verification=verification),
                status=status.HTTP_200_OK,
            )


class MembershipOrderCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def get(self, request):
        orders = (
            PaymentOrder.objects.filter(
                user=request.user,
                order_type=PaymentOrder.TYPE_MEMBERSHIP,
            )
            .order_by('-created_at', '-id')
        )
        serializer = MembershipOrderSerializer(orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = MembershipOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.validated_data['plan']
        payment_asset = serializer.validated_data.get('payment_asset', PaymentOrder.PAYMENT_ASSET_THB_LTT)
        service = MembershipOrderService()
        try:
            order, reused = service.create_order_with_payment_asset(user=request.user, plan=plan, payment_asset=payment_asset)
        except LbryDaemonConnectionError as exc:
            logger.exception('membership_order_create daemon_connection_error user_id=%s', request.user.id)
            return Response({'detail': 'Membership payment service is temporarily unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except LbryDaemonInvalidParamsError as exc:
            detail = str(exc) or 'Invalid membership payment parameters.'
            if payment_asset in {PaymentOrder.PAYMENT_ASSET_MEOW_POINTS, PaymentOrder.PAYMENT_ASSET_MEOW_CREDIT}:
                return Response({'detail': detail}, status=status.HTTP_400_BAD_REQUEST)
            logger.exception('membership_order_create daemon_invalid_params user_id=%s', request.user.id)
            return Response({'detail': 'Membership payment service is temporarily unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except LbryDaemonRpcError as exc:
            logger.exception('membership_order_create daemon_rpc_error user_id=%s', request.user.id)
            return Response({'detail': 'Membership payment service is temporarily unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except WalletAddressConflictError as exc:
            logger.exception('membership_order_create duplicate_wallet_address user_id=%s', request.user.id)
            return Response({'detail': 'Membership payment service is temporarily unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except MembershipOrderPersistenceError as exc:
            logger.exception('membership_order_create persistence_error user_id=%s', request.user.id)
            return Response({'detail': 'Membership payment service is temporarily unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except LbryDaemonError as exc:
            logger.exception('membership_order_create daemon_error user_id=%s', request.user.id)
            return Response({'detail': 'Membership payment service is temporarily unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        response_serializer = MembershipOrderSerializer(order)
        response_payload = dict(response_serializer.data)
        if reused:
            response_payload['reused'] = True
            return Response(response_payload, status=status.HTTP_200_OK)
        response_payload['reused'] = False
        return Response(response_payload, status=status.HTTP_201_CREATED)


class MembershipOrderDetailAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, order_no):
        order = generics.get_object_or_404(
            PaymentOrder.objects.filter(
                user=request.user,
                order_type=PaymentOrder.TYPE_MEMBERSHIP,
            ),
            order_no=order_no,
        )
        serializer = MembershipOrderSerializer(order)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MembershipOrderTxHintAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_no):
        order = generics.get_object_or_404(
            PaymentOrder.objects.filter(
                user=request.user,
                order_type=PaymentOrder.TYPE_MEMBERSHIP,
            ),
            order_no=order_no,
        )
        serializer = MembershipOrderTxHintSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if order.payment_method_code == PaymentOrder.PAYMENT_METHOD_PLATFORM_ASSET:
            return Response({'detail': 'tx-hint is not supported for platform asset orders.'}, status=status.HTTP_400_BAD_REQUEST)

        hint_txid = serializer.validated_data['txid']
        if order.status in {PaymentOrder.STATUS_PENDING, PaymentOrder.STATUS_EXPIRED, PaymentOrder.STATUS_UNDERPAID}:
            order.txid = hint_txid
            order.save(update_fields=['txid', 'updated_at'])
        return Response(
            {
                'order_no': order.order_no,
                'txid_hint': hint_txid,
                'status': order.status,
                'detail': 'txid hint recorded; on-chain verification is still required.',
            },
            status=status.HTTP_200_OK,
        )


class MembershipOrderVerifyNowAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, order_no):
        order = generics.get_object_or_404(
            PaymentOrder.objects.filter(
                user=request.user,
                order_type=PaymentOrder.TYPE_MEMBERSHIP,
            ),
            order_no=order_no,
        )
        try:
            if order.payment_method_code == PaymentOrder.PAYMENT_METHOD_PLATFORM_ASSET:
                return Response({'detail': 'verify-now is not supported for platform asset orders.'}, status=status.HTTP_400_BAD_REQUEST)
            verification = PaymentDetectionService().verify_order_once(order=order, txid_hint=order.txid)
        except LbryDaemonError:
            return Response({'detail': 'Verification attempt failed.'}, status=status.HTTP_502_BAD_GATEWAY)
        order.refresh_from_db()
        order_payload = MembershipOrderSerializer(order).data
        return Response(
            {
                'order': order_payload,
                'verification': verification,
                'detail': 'Verification attempted. Paid status depends on chain confirmations and output matching.',
            },
            status=status.HTTP_200_OK,
        )


class WalletPrototypePayOrderAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        serializer = WalletPrototypePayOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = generics.get_object_or_404(
            PaymentOrder.objects.filter(order_type__in=[PaymentOrder.TYPE_MEMBERSHIP, PaymentOrder.TYPE_PRODUCT]),
            order_no=serializer.validated_data['order_no'],
            user=request.user,
        )
        if order.order_type == PaymentOrder.TYPE_MEMBERSHIP:
            if order.status not in {PaymentOrder.STATUS_PENDING, PaymentOrder.STATUS_EXPIRED, PaymentOrder.STATUS_UNDERPAID}:
                return Response({'detail': 'Order is not payable.'}, status=status.HTTP_400_BAD_REQUEST)
            if order.expires_at and order.expires_at < timezone.now() and order.status == PaymentOrder.STATUS_PENDING:
                return Response({'detail': 'Order has expired.'}, status=status.HTTP_400_BAD_REQUEST)
        elif order.order_type == PaymentOrder.TYPE_PRODUCT:
            product_order = ProductOrder.objects.filter(payment_order=order, buyer=request.user).first()
            if not product_order:
                return Response({'detail': 'Order is not payable.'}, status=status.HTTP_400_BAD_REQUEST)
            if product_order.status != ProductOrder.STATUS_PENDING_PAYMENT:
                return Response({'detail': 'Order is not payable.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'detail': 'Unsupported order type.'}, status=status.HTTP_400_BAD_REQUEST)

        wallet_id = (serializer.validated_data.get('wallet_id') or request.user.linked_wallet_id or '').strip()
        if not wallet_id:
            return Response({'detail': 'Missing linked wallet.'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.linked_wallet_id and wallet_id != request.user.linked_wallet_id:
            return Response({'detail': 'Wallet mismatch for user.'}, status=status.HTTP_400_BAD_REQUEST)

        service = WalletPrototypePayOrderService()
        try:
            logger.info(
                'wallet_prototype_membership_submit order_no=%s order_type=%s wallet_id=%s amount=%s pay_to_address=%s method=%s',
                order.order_no,
                order.order_type,
                wallet_id,
                order.expected_amount_lbc,
                order.pay_to_address,
                'WalletPrototypePayOrderService.pay_payment_order',
            )
            result = service.pay_payment_order(
                user=request.user,
                order=order,
                wallet_id=wallet_id,
                password=serializer.validated_data['password'],
            )
        except WalletPrototypeValidationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except WalletPrototypeError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        verification = None
        txid_hint = (result.get('txid') or '').strip()
        if txid_hint:
            try:
                verification = PaymentDetectionService().verify_order_once(order=order, txid_hint=txid_hint)
            except LbryDaemonError:
                verification = {'verified': False, 'message': 'verification_attempt_failed'}
        result['verification'] = verification
        return Response(result, status=status.HTTP_200_OK)


class WalletPrototypePayProductOrderAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        serializer = WalletPrototypePayProductOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = generics.get_object_or_404(
            ProductOrder.objects.select_related('payment_order'),
            order_no=serializer.validated_data['order_no'],
            buyer=request.user,
        )
        if order.status != ProductOrder.STATUS_PENDING_PAYMENT:
            return Response({'detail': 'Product order is not pending payment.'}, status=status.HTTP_409_CONFLICT)
        payment_order = order.payment_order
        if payment_order is None or payment_order.order_type != PaymentOrder.TYPE_PRODUCT:
            return Response({'detail': 'Invalid product payment order linkage.'}, status=status.HTTP_400_BAD_REQUEST)
        existing_txid = (payment_order.txid or '').strip()
        if existing_txid:
            return Response(
                {
                    'detail': 'Payment already submitted and is waiting for confirmation.',
                    'order_no': order.order_no,
                    'txid': existing_txid,
                    'payment_order_status': payment_order.status,
                    'product_order_status': order.status,
                    'confirmations': payment_order.confirmations,
                },
                status=status.HTTP_200_OK,
            )
        if not (payment_order.pay_to_address or '').strip():
            return Response({'detail': 'Product payment order is missing pay_to_address.'}, status=status.HTTP_400_BAD_REQUEST)
        if payment_order.expected_amount_lbc is None or payment_order.expected_amount_lbc <= 0:
            return Response({'detail': 'Product payment order is missing expected_amount_lbc.'}, status=status.HTTP_400_BAD_REQUEST)
        wallet_id = (serializer.validated_data.get('wallet_id') or request.user.linked_wallet_id or '').strip()
        if not wallet_id:
            return Response({'detail': 'Missing linked wallet.'}, status=status.HTTP_400_BAD_REQUEST)
        if request.user.linked_wallet_id and wallet_id != request.user.linked_wallet_id:
            return Response({'detail': 'Wallet mismatch for user.'}, status=status.HTTP_400_BAD_REQUEST)

        service = WalletPrototypePayOrderService()
        try:
            send_amount = payment_order.expected_amount_lbc
            logger.info(
                'wallet_prototype_product_submit order_no=%s order_type=%s wallet_id=%s amount=%s pay_to_address=%s method=%s',
                payment_order.order_no,
                payment_order.order_type,
                wallet_id,
                send_amount,
                payment_order.pay_to_address,
                'WalletPrototypePayOrderService.pay_payment_order',
            )
            result = service.pay_payment_order(
                user=request.user,
                order=payment_order,
                wallet_id=wallet_id,
                password=serializer.validated_data['password'],
                amount_override=send_amount,
            )
        except WalletPrototypeValidationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except WalletPrototypeError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                'order_no': order.order_no,
                'txid': result.get('txid', ''),
                'detail': result.get('detail', 'Payment submitted. Waiting for on-chain confirmation.'),
                'payment_order_status': result.get('payment_order_status', payment_order.status),
                'product_order_status': result.get('product_order_status', order.status),
                'confirmations': result.get('confirmations', payment_order.confirmations),
                'wallet_relocked': bool(result.get('wallet_relocked')),
            },
            status=status.HTTP_200_OK,
        )


class MembershipMeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        membership = UserMembership.objects.filter(user=request.user).select_related('plan').order_by('-ends_at', '-id').first()
        serializer = MyMembershipSerializer.from_membership(membership)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PublicVideoCommentListAPIView(generics.ListAPIView):
    serializer_class = VideoCommentSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = CommentPagination

    def get_queryset(self):
        video = generics.get_object_or_404(
            Video,
            pk=self.kwargs['pk'],
            visibility=Video.VISIBILITY_PUBLIC,
            status=Video.STATUS_ACTIVE,
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
            Video.objects.filter(
                visibility=Video.VISIBILITY_PUBLIC,
                status=Video.STATUS_ACTIVE,
            ),
            pk=pk,
        )
        viewer = request.user if request.user.is_authenticated else None
        VideoView.objects.create(video=video, viewer=viewer)
        video = annotate_videos_for_request(Video.objects.filter(pk=video.pk), request).get()
        serializer = VideoSerializer(
            video,
            context={
                'request': request,
                'mask_locked_file_fields': True,
            },
        )
        return Response(serializer.data, status=status.HTTP_200_OK)


class PublicCategoryListAPIView(generics.ListAPIView):
    serializer_class = PublicCategorySerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        return Category.objects.filter(is_active=True).exclude(
            slug__in=LEGACY_CATEGORY_SLUG_ALIASES.keys()
        ).order_by('sort_order', 'name')
