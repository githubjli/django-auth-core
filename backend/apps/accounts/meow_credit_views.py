from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import MeowCreditLedger, MeowCreditPackage, MeowCreditRecharge, PaymentOrder
from apps.accounts.drama_views import DramaSeriesPagination
from apps.accounts.meow_credit_serializers import (
    MeowCreditLedgerSerializer,
    MeowCreditPackageSerializer,
    MeowCreditRechargeCreateSerializer,
    MeowCreditRechargeSerializer,
    MeowCreditRechargeTxHintSerializer,
    MeowCreditRedeemCreateSerializer,
    MeowCreditRedeemRequestSerializer,
    MeowCreditWalletSerializer,
)
from apps.accounts.services import MeowCreditRechargeService, MeowCreditService


class MeowCreditWalletAPIView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditWalletSerializer

    def get_object(self):
        return MeowCreditService.get_or_create_wallet(self.request.user)


class MeowCreditPackageListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditPackageSerializer

    def get_queryset(self):
        return MeowCreditPackage.objects.filter(status=MeowCreditPackage.STATUS_ACTIVE).order_by('sort_order', 'id')


class MeowCreditLedgerListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditLedgerSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        return MeowCreditLedger.objects.filter(user=self.request.user).order_by('-created_at', '-id')


class MeowCreditRechargeListCreateAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditRechargeSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        queryset = MeowCreditRecharge.objects.filter(user=self.request.user).select_related('payment_order').order_by('-created_at', '-id')
        for recharge in queryset:
            MeowCreditRechargeService().credit_paid_recharge(recharge)
        return queryset

    def post(self, request):
        serializer = MeowCreditRechargeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            recharge = MeowCreditRechargeService().create_order(user=request.user, package_code=serializer.validated_data['package_code'])
        except DjangoValidationError as exc:
            raise serializers.ValidationError(getattr(exc, 'message_dict', getattr(exc, 'messages', str(exc))))
        return Response(MeowCreditRechargeSerializer(recharge).data, status=status.HTTP_201_CREATED)


class MeowCreditRechargeDetailAPIView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditRechargeSerializer
    lookup_field = 'order_no'

    def get_queryset(self):
        return MeowCreditRecharge.objects.filter(user=self.request.user).select_related('payment_order')

    def get_object(self):
        recharge = super().get_object()
        MeowCreditRechargeService().credit_paid_recharge(recharge)
        recharge.refresh_from_db()
        return recharge


class MeowCreditRechargeTxHintAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditRechargeTxHintSerializer

    def post(self, request, order_no):
        recharge = generics.get_object_or_404(
            MeowCreditRecharge.objects.select_related('payment_order'),
            user=request.user,
            order_no=order_no,
        )
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        txid_hint = serializer.validated_data['txid']
        payment_order = recharge.payment_order
        if payment_order and payment_order.status in {
            PaymentOrder.STATUS_PENDING,
            PaymentOrder.STATUS_EXPIRED,
            PaymentOrder.STATUS_UNDERPAID,
        }:
            payment_order.txid = txid_hint
            payment_order.save(update_fields=['txid', 'updated_at'])
        return Response(
            {
                'order_no': recharge.order_no,
                'txid_hint': txid_hint,
                'status': recharge.status,
                'detail': 'txid hint recorded; payment confirmation is still required.',
            },
            status=status.HTTP_200_OK,
        )


class MeowCreditRedeemListCreateAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditRedeemRequestSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        return self.request.user.meow_credit_redeem_requests.order_by('-created_at', '-id')

    def post(self, request):
        serializer = MeowCreditRedeemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            redeem = MeowCreditService.create_redeem_request(
                user=request.user,
                amount=serializer.validated_data['amount'],
                redeem_method=serializer.validated_data['redeem_method'],
                account_snapshot=serializer.validated_data.get('account_snapshot') or {},
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(getattr(exc, 'message_dict', getattr(exc, 'messages', str(exc))))
        return Response(MeowCreditRedeemRequestSerializer(redeem).data, status=status.HTTP_201_CREATED)
