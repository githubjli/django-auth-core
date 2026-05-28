from rest_framework import serializers

from apps.accounts.models import MeowPointLedger, MeowPointPackage, MeowPointPurchase, MeowPointWallet


class MeowPointWalletSerializer(serializers.ModelSerializer):
    balance = serializers.SerializerMethodField()
    total_earned = serializers.SerializerMethodField()
    total_spent = serializers.SerializerMethodField()
    total_purchased = serializers.SerializerMethodField()
    total_bonus = serializers.SerializerMethodField()

    class Meta:
        model = MeowPointWallet
        fields = (
            'balance',
            'total_earned',
            'total_spent',
            'total_purchased',
            'total_bonus',
            'created_at',
            'updated_at',
        )

    @staticmethod
    def _to_legacy_int(value):
        if value is None:
            return 0
        return int(value)

    def get_balance(self, obj):
        return self._to_legacy_int(obj.balance)

    def get_total_earned(self, obj):
        return self._to_legacy_int(obj.total_earned)

    def get_total_spent(self, obj):
        return self._to_legacy_int(obj.total_spent)

    def get_total_purchased(self, obj):
        return self._to_legacy_int(obj.total_purchased)

    def get_total_bonus(self, obj):
        return self._to_legacy_int(obj.total_bonus)


class MeowPointPackageSerializer(serializers.ModelSerializer):
    total_points = serializers.SerializerMethodField()

    class Meta:
        model = MeowPointPackage
        fields = (
            'code',
            'name',
            'points_amount',
            'bonus_points',
            'total_points',
            'price_amount',
            'price_currency',
            'status',
            'sort_order',
            'description',
        )

    def get_total_points(self, obj):
        return obj.points_amount + obj.bonus_points


class MeowPointLedgerSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeowPointLedger
        fields = (
            'id',
            'entry_type',
            'amount',
            'balance_before',
            'balance_after',
            'target_type',
            'target_id',
            'payment_order_id',
            'note',
            'created_at',
        )


class MeowPointOrderCreateSerializer(serializers.Serializer):
    package_code = serializers.CharField(max_length=64)

    def validate_package_code(self, value):
        package_code = value.strip()
        if not package_code:
            raise serializers.ValidationError('package_code is required.')
        return package_code


class MeowPointPurchaseSerializer(serializers.ModelSerializer):
    payment_order_status = serializers.CharField(source='payment_order.status', read_only=True)
    txid = serializers.CharField(source='payment_order.txid', read_only=True)

    class Meta:
        model = MeowPointPurchase
        fields = (
            'order_no',
            'package_code_snapshot',
            'package_name_snapshot',
            'points_amount',
            'bonus_points',
            'total_points',
            'price_amount',
            'price_currency',
            'status',
            'payment_order_status',
            'txid',
            'paid_at',
            'credited_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class MeowPointOrderTxHintSerializer(serializers.Serializer):
    txid = serializers.CharField(max_length=128)

    def validate_txid(self, value):
        txid = value.strip()
        if not txid:
            raise serializers.ValidationError('txid is required.')
        return txid
