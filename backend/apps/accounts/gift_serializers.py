from rest_framework import serializers

from apps.accounts.models import Gift, GiftTransaction


class GiftSerializer(serializers.ModelSerializer):
    icon_url = serializers.SerializerMethodField()
    animation_url = serializers.SerializerMethodField()

    class Meta:
        model = Gift
        fields = (
            'code',
            'name',
            'icon_url',
            'animation_url',
            'points_price',
            'is_active',
            'sort_order',
        )

    def _build_file_url(self, file_field):
        if not file_field:
            return None
        request = self.context.get('request')
        if request is None:
            return file_field.url
        return request.build_absolute_uri(file_field.url)

    def get_icon_url(self, obj):
        return self._build_file_url(obj.icon)

    def get_animation_url(self, obj):
        return self._build_file_url(obj.animation)


class GiftSendSerializer(serializers.Serializer):
    gift_code = serializers.CharField(max_length=64)
    quantity = serializers.IntegerField(min_value=1)


class GiftTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GiftTransaction
        fields = (
            'id',
            'gift_name_snapshot',
            'points_price_snapshot',
            'quantity',
            'total_points',
            'created_at',
        )
