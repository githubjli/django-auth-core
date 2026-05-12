from rest_framework import serializers

from apps.accounts.constants import TOKEN_SYMBOL
from apps.accounts.models import (
    MeowCreditLedger,
    MeowCreditPackage,
    MeowCreditRecharge,
    MeowCreditRedeemRequest,
    MeowCreditWallet,
)


class MeowCreditWalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeowCreditWallet
        fields = (
            'balance',
            'total_recharged',
            'total_spent',
            'total_redeemed',
            'total_adjusted',
            'created_at',
            'updated_at',
        )


class MeowCreditPackageSerializer(serializers.ModelSerializer):
    total_credit = serializers.SerializerMethodField()
    display_currency = serializers.SerializerMethodField()

    class Meta:
        model = MeowCreditPackage
        fields = (
            'code',
            'name',
            'credit_amount',
            'bonus_credit',
            'total_credit',
            'price_amount',
            'price_currency',
            'display_currency',
            'status',
            'sort_order',
            'description',
        )

    def get_total_credit(self, obj):
        return obj.credit_amount + obj.bonus_credit

    def get_display_currency(self, obj):
        return obj.price_currency or TOKEN_SYMBOL


class MeowCreditLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeowCreditLedger
        fields = (
            'id',
            'entry_type',
            'status',
            'amount',
            'balance_before',
            'balance_after',
            'target_type',
            'target_id',
            'payment_order_id',
            'note',
            'created_at',
        )


class MeowCreditRechargeInfoQuerySerializer(serializers.Serializer):
    package_code = serializers.CharField(max_length=64)

    def validate_package_code(self, value):
        package_code = value.strip()
        if not package_code:
            raise serializers.ValidationError('package_code is required.')
        return package_code


class MeowCreditRechargeSubmitTxidSerializer(serializers.Serializer):
    package_code = serializers.CharField(max_length=64)
    txid = serializers.CharField(max_length=128)

    def validate_package_code(self, value):
        package_code = value.strip()
        if not package_code:
            raise serializers.ValidationError('package_code is required.')
        return package_code

    def validate_txid(self, value):
        txid = value.strip()
        if not txid:
            raise serializers.ValidationError('txid is required.')
        return txid


class MeowCreditRechargeCreateSerializer(serializers.Serializer):
    package_code = serializers.CharField(max_length=64)

    def validate_package_code(self, value):
        package_code = value.strip()
        if not package_code:
            raise serializers.ValidationError('package_code is required.')
        return package_code


class MeowCreditRechargeSerializer(serializers.ModelSerializer):
    display_currency = serializers.SerializerMethodField()
    expected_amount = serializers.SerializerMethodField()
    pay_to_address = serializers.CharField(source='payment_order.pay_to_address', read_only=True)
    expires_at = serializers.DateTimeField(source='payment_order.expires_at', read_only=True)
    payment_order_status = serializers.CharField(source='payment_order.status', read_only=True)
    txid = serializers.CharField(source='payment_order.txid', read_only=True)

    class Meta:
        model = MeowCreditRecharge
        fields = (
            'order_no',
            'credit_amount',
            'bonus_credit',
            'total_credit',
            'price_amount',
            'price_currency',
            'display_currency',
            'expected_amount',
            'pay_to_address',
            'expires_at',
            'status',
            'payment_order_status',
            'txid',
            'paid_at',
            'credited_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_display_currency(self, obj):
        return obj.price_currency or TOKEN_SYMBOL

    def get_expected_amount(self, obj):
        payment_order = getattr(obj, 'payment_order', None)
        value = obj.price_amount
        if payment_order and payment_order.expected_amount_lbc is not None:
            value = payment_order.expected_amount_lbc
        return f'{value:.2f}'


class MeowCreditRechargeTxHintSerializer(serializers.Serializer):
    txid = serializers.CharField(max_length=128)

    def validate_txid(self, value):
        txid = value.strip()
        if not txid:
            raise serializers.ValidationError('txid is required.')
        return txid


class MeowCreditRedeemCreateSerializer(serializers.Serializer):
    amount = serializers.IntegerField(min_value=1)
    redeem_method = serializers.CharField(max_length=64)
    account_snapshot = serializers.JSONField(default=dict)

    def validate_redeem_method(self, value):
        method = value.strip()
        if not method:
            raise serializers.ValidationError('redeem_method is required.')
        return method


class MeowCreditRedeemRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeowCreditRedeemRequest
        fields = (
            'redeem_no',
            'amount',
            'status',
            'redeem_method',
            'account_snapshot',
            'reviewed_at',
            'reject_reason',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields
