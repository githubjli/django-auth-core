from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import generics
from rest_framework import status
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.drama_views import DramaSeriesPagination
from apps.accounts.meow_points_serializers import (
    MeowPointLedgerSerializer,
    MeowPointOrderCreateSerializer,
    MeowPointOrderTxHintSerializer,
    MeowPointPackageSerializer,
    MeowPointPurchaseSerializer,
    MeowPointWalletSerializer,
)
from apps.accounts.models import MeowPointLedger, MeowPointPackage, MeowPointPurchase, PaymentOrder
from apps.accounts.services import MeowPointPurchaseService, MeowPointService


class MeowPointWalletAPIView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowPointWalletSerializer

    def get_object(self):
        return MeowPointService.get_or_create_wallet(self.request.user)


class MeowPointPackageListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowPointPackageSerializer

    def get_queryset(self):
        return MeowPointPackage.objects.filter(status=MeowPointPackage.STATUS_ACTIVE).order_by('sort_order', 'id')


class MeowPointLedgerListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowPointLedgerSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        return MeowPointLedger.objects.filter(user=self.request.user).order_by('-created_at', '-id')


class MeowPointOrderListCreateAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowPointPurchaseSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        queryset = MeowPointPurchase.objects.filter(user=self.request.user).select_related('payment_order').order_by('-created_at', '-id')
        for purchase in queryset:
            MeowPointPurchaseService().credit_paid_purchase(purchase)
        return queryset

    def post(self, request):
        serializer = MeowPointOrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            purchase = MeowPointPurchaseService().create_order(user=request.user, package_code=serializer.validated_data['package_code'])
        except DjangoValidationError as exc:
            raise serializers.ValidationError(getattr(exc, 'message_dict', getattr(exc, 'messages', str(exc))))
        response_serializer = MeowPointPurchaseSerializer(purchase)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class MeowPointOrderDetailAPIView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowPointPurchaseSerializer
    lookup_field = 'order_no'

    def get_queryset(self):
        return MeowPointPurchase.objects.filter(user=self.request.user).select_related('payment_order')

    def get_object(self):
        purchase = super().get_object()
        MeowPointPurchaseService().credit_paid_purchase(purchase)
        purchase.refresh_from_db()
        return purchase


class MeowPointOrderTxHintAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowPointOrderTxHintSerializer

    def post(self, request, order_no):
        purchase = generics.get_object_or_404(
            MeowPointPurchase.objects.select_related('payment_order'),
            user=request.user,
            order_no=order_no,
        )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        txid_hint = serializer.validated_data['txid']
        payment_order = purchase.payment_order
        if payment_order and payment_order.status in {
            PaymentOrder.STATUS_PENDING,
            PaymentOrder.STATUS_EXPIRED,
            PaymentOrder.STATUS_UNDERPAID,
        }:
            payment_order.txid = txid_hint
            payment_order.save(update_fields=['txid', 'updated_at'])

        return Response(
            {
                'order_no': purchase.order_no,
                'txid_hint': txid_hint,
                'status': purchase.status,
                'detail': 'txid hint recorded; payment confirmation is still required.',
            },
            status=status.HTTP_200_OK,
        )


class DailyLoginRewardClaimAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        result = MeowPointService.grant_daily_login_reward(user=request.user)
        return Response(result, status=status.HTTP_200_OK)
