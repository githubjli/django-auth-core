from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
import logging
from rest_framework import generics, serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.constants import TOKEN_SYMBOL
from apps.accounts.models import MeowCreditLedger, MeowCreditPackage, MeowCreditRecharge, PaymentOrder
from apps.accounts.drama_views import DramaSeriesPagination
from apps.accounts.meow_credit_serializers import (
    MeowCreditLedgerSerializer,
    MeowCreditPackageSerializer,
    MeowCreditRechargeCreateSerializer,
    MeowCreditRechargeInfoQuerySerializer,
    MeowCreditRechargeSerializer,
    MeowCreditRechargeSubmitTxidSerializer,
    MeowCreditRechargeTxHintSerializer,
    MeowCreditRedeemCreateSerializer,
    MeowCreditRedeemRequestSerializer,
    MeowCreditWalletSerializer,
)
from apps.accounts.services import LbryDaemonError, MeowCreditPaymentDetectionService, MeowCreditRechargeService, MeowCreditService


logger = logging.getLogger(__name__)


class MeowCreditWalletAPIView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditWalletSerializer

    def get_object(self):
        wallet, created = MeowCreditService.get_or_create_wallet_with_flag(self.request.user)
        if created:
            logger.warning('unexpected meow credit wallet auto-created user_id=%s', self.request.user.id)
        return wallet


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


class MeowCreditRechargeInfoAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = MeowCreditRechargeInfoQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        package = generics.get_object_or_404(
            MeowCreditPackage.objects.filter(status=MeowCreditPackage.STATUS_ACTIVE),
            code=serializer.validated_data['package_code'],
        )
        pay_to_address = (settings.LBRY_PLATFORM_RECEIVE_ADDRESS or '').strip()
        if not pay_to_address:
            return Response({'detail': 'Meow Credit payment address is not configured.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        expected_amount = f'{package.price_amount:.2f}'
        currency = TOKEN_SYMBOL
        return Response(
            {
                'package_code': package.code,
                'package_name': package.name,
                'credit_amount': package.credit_amount,
                'bonus_credit': package.bonus_credit,
                'total_credit': package.credit_amount + package.bonus_credit,
                'price_amount': expected_amount,
                'price_currency': currency,
                'display_currency': currency,
                'expected_amount': expected_amount,
                'pay_to_address': pay_to_address,
                'required_confirmations': 0,
                'notice': (
                    f'Send the exact {expected_amount} {currency} amount to the platform address, '
                    'then submit your txid for verification.'
                ),
            },
            status=status.HTTP_200_OK,
        )


class MeowCreditRechargeSubmitTxidAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditRechargeSubmitTxidSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            recharge, created = MeowCreditRechargeService().submit_txid(
                user=request.user,
                package_code=serializer.validated_data['package_code'],
                txid=serializer.validated_data['txid'],
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError(getattr(exc, 'message_dict', getattr(exc, 'messages', str(exc))))
        verification = self._verify_recharge_once(recharge)
        if verification.get('verified'):
            recharge = MeowCreditRecharge.objects.select_related('payment_order').get(pk=recharge.pk)
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        payload = dict(MeowCreditRechargeSerializer(recharge).data)
        payload['verification'] = verification
        return Response(payload, status=response_status)

    def _verify_recharge_once(self, recharge):
        try:
            return MeowCreditPaymentDetectionService().verify_recharge_once(recharge=recharge)
        except LbryDaemonError:
            payment_order = recharge.payment_order
            return {
                'verified': False,
                'matched': False,
                'paid': False,
                'status': payment_order.status if payment_order else recharge.status,
                'recharge_status': recharge.status,
                'confirmations': payment_order.confirmations if payment_order else 0,
                'txid': payment_order.txid if payment_order else '',
                'reason': 'chain_lookup_failed',
            }


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


class MeowCreditRechargeVerifyNowAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowCreditRechargeTxHintSerializer

    def post(self, request, order_no):
        recharge = generics.get_object_or_404(
            MeowCreditRecharge.objects.select_related('payment_order'),
            user=request.user,
            order_no=order_no,
        )
        txid_hint = None
        if request.data:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            txid_hint = serializer.validated_data['txid']
        try:
            verification = MeowCreditPaymentDetectionService().verify_recharge_once(
                recharge=recharge,
                txid_hint=txid_hint,
            )
        except LbryDaemonError:
            return Response({'detail': 'Verification attempt failed.'}, status=status.HTTP_502_BAD_GATEWAY)
        recharge = MeowCreditRecharge.objects.select_related('payment_order').get(pk=recharge.pk)
        return Response(
            {
                'recharge': MeowCreditRechargeSerializer(recharge).data,
                'verification': verification,
                'detail': 'Verification attempted. Crediting depends on chain confirmations and output matching.',
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
