from rest_framework import serializers

from apps.accounts.models import MeowPointLedger, MeowPointPackage, MeowPointWallet


class MeowPointWalletSerializer(serializers.ModelSerializer):
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
