from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.db import IntegrityError
from django.db.models import Count, Exists, F, OuterRef, Q
from datetime import timedelta
import json
import hmac
import logging
from asgiref.sync import async_to_sync
from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.accounts.models import (
    BillingPlan,
    BillingSubscription,
    Category,
    ChannelSubscription,
    CommentLike,
    LiveChatMessage,
    LiveChatRoom,
    LiveStream,
    LiveStreamProduct,
    MembershipPlan,
    PaymentOrder,
    Product,
    ProductOrder,
    ProductRefundRequest,
    SellerPayout,
    SellerPayoutAddress,
    SellerStore,
    StreamPaymentMethod,
    UserShippingAddress,
    UserMembership,
    Video,
    VideoComment,
    VideoLike,
    VideoView,
    generate_stream_key,
)
from apps.accounts.permissions import IsCreator, IsStaffOrSuperuser
from apps.accounts.serializers import (
    AccountPasswordChangeSerializer,
    AccountPreferencesSerializer,
    AccountProfileSerializer,
    AdminUserSerializer,
    AdminVideoSerializer,
    BillingPlanSerializer,
    BillingSubscriptionCreateSerializer,
    BillingSubscriptionSerializer,
    MembershipOrderCreateSerializer,
    MembershipOrderTxHintSerializer,
    MembershipOrderSerializer,
    MembershipPlanSerializer,
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
    ProductOrderTxHintSerializer,
    ProductRefundAdminActionSerializer,
    ProductRefundRequestCreateSerializer,
    ProductRefundRequestSerializer,
    SellerPayoutAddressSerializer,
    SellerProductOrderListSerializer,
    PaymentOrderCreateSerializer,
    PaymentOrderSerializer,
    RegisterSerializer,
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
from apps.accounts.services import (
    ActiveMembershipExistsError,
    AntMediaLiveAdapter,
    LbryDaemonConnectionError,
    LbryDaemonError,
    LbryDaemonInvalidParamsError,
    LbryDaemonRpcError,
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
        serializer = ProductOrderDetailSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ProductOrderCreateSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        service = ProductOrderService()
        try:
            order = service.create_order(
                buyer=request.user,
                product=serializer.validated_data['product'],
                quantity=serializer.validated_data['quantity'],
                shipping_address=serializer.validated_data['shipping_address'],
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
        payout = getattr(order, 'seller_payout', None)
        if payout and payout.status == SellerPayout.STATUS_PENDING:
            payout.status = SellerPayout.STATUS_FAILED
            payout.failure_note = 'refund_marked'
            payout.save(update_fields=['status', 'failure_note', 'updated_at'])
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
            Video.objects.filter(visibility=Video.VISIBILITY_PUBLIC),
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
            Video.objects.filter(visibility=Video.VISIBILITY_PUBLIC),
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


class CreatorFollowAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        creator = generics.get_object_or_404(User, pk=pk)
        if creator.pk == request.user.pk:
            return Response({'detail': 'You cannot follow yourself.'}, status=status.HTTP_400_BAD_REQUEST)

        _, created = ChannelSubscription.objects.get_or_create(channel=creator, subscriber=request.user)
        if created:
            User.objects.filter(pk=creator.pk).update(subscriber_count=F('subscriber_count') + 1)
        creator.refresh_from_db(fields=['subscriber_count'])
        return Response(
            {
                'creator_id': creator.pk,
                'follower_count': creator.subscriber_count,
                'viewer_is_following': True,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        creator = generics.get_object_or_404(User, pk=pk)
        deleted_count, _ = ChannelSubscription.objects.filter(channel=creator, subscriber=request.user).delete()
        if deleted_count:
            User.objects.filter(pk=creator.pk, subscriber_count__gt=0).update(subscriber_count=F('subscriber_count') - 1)
        creator.refresh_from_db(fields=['subscriber_count'])
        return Response(
            {
                'creator_id': creator.pk,
                'follower_count': creator.subscriber_count,
                'viewer_is_following': False,
            },
            status=status.HTTP_200_OK,
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


class MembershipOrderCreateAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [JSONParser, FormParser]

    def post(self, request):
        serializer = MembershipOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = serializer.validated_data['plan']
        service = MembershipOrderService()
        try:
            order, reused = service.create_order(user=request.user, plan=plan)
        except ActiveMembershipExistsError as exc:
            membership = exc.membership
            payload = {
                'code': 'active_membership_exists',
                'detail': 'You already have an active membership. Additional membership purchases are not available yet.',
            }
            if membership is not None and membership.plan_id:
                payload['current_membership'] = {
                    'plan': {
                        'id': membership.plan_id,
                        'code': membership.plan.code,
                        'name': membership.plan.name,
                    },
                    'valid_until': membership.ends_at,
                }
            return Response(payload, status=status.HTTP_409_CONFLICT)
        except LbryDaemonConnectionError as exc:
            logger.exception('membership_order_create daemon_connection_error user_id=%s', request.user.id)
            return Response({'detail': 'Membership payment service is temporarily unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except LbryDaemonInvalidParamsError as exc:
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
