from urllib.parse import urljoin

from django.conf import settings
from rest_framework import serializers

from apps.accounts.models import Gift, GiftTransaction


class GiftSerializer(serializers.ModelSerializer):
    emoji = serializers.SerializerMethodField()
    coin_cost = serializers.IntegerField(source='points_price', read_only=True)
    icon_url = serializers.SerializerMethodField()
    animation_url = serializers.SerializerMethodField()

    class Meta:
        model = Gift
        fields = (
            'id',
            'code',
            'name',
            'emoji',
            'coin_cost',
            'points_price',
            'icon_url',
            'animation_url',
            'is_active',
            'sort_order',
        )

    def _build_file_url(self, file_field):
        if not file_field:
            return None
        file_url = file_field.url
        public_media_base_url = getattr(settings, 'PUBLIC_MEDIA_BASE_URL', '').rstrip('/')
        if public_media_base_url:
            return urljoin(f'{public_media_base_url}/', file_url.lstrip('/'))
        request = self.context.get('request')
        if request is None:
            return file_url
        return request.build_absolute_uri(file_url)

    def get_emoji(self, obj):
        return {
            'rose': '🌹',
            'star': '⭐',
            'crown': '👑',
            'diamond': '💎',
        }.get(obj.code, '🎁')

    def get_emoji(self, obj):
        return {
            'rose': '🌹',
            'star': '⭐',
            'crown': '👑',
            'diamond': '💎',
        }.get(obj.code, '🎁')

    def get_icon_url(self, obj):
        return self._build_file_url(obj.icon)

    def get_animation_url(self, obj):
        return self._build_file_url(obj.animation)


class GiftSendSerializer(serializers.Serializer):
    gift_id = serializers.IntegerField(required=False, min_value=1)
    gift_code = serializers.CharField(max_length=64, required=False, allow_blank=False)
    quantity = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        if not attrs.get('gift_id') and not attrs.get('gift_code'):
            raise serializers.ValidationError({'gift_code': ['gift_id or gift_code is required.']})
        return attrs


class ContentGiftSendSerializer(serializers.Serializer):
    ALLOWED_AMOUNTS = [1, 10, 30, 100, 200, 500]

    amount = serializers.ChoiceField(choices=ALLOWED_AMOUNTS)
    payment_method = serializers.ChoiceField(
        choices=['meow_points', 'meow_credit'],
        required=False,
        default='meow_points',
    )


class ContentGiftSendResponseSerializer(serializers.Serializer):
    video_id = serializers.IntegerField(required=False)
    series_id = serializers.IntegerField(required=False)
    receiver_id = serializers.IntegerField()
    amount = serializers.IntegerField()
    payment_method = serializers.CharField()
    points_charged = serializers.IntegerField()
    credits_charged = serializers.IntegerField()
    sender_balance = serializers.IntegerField()
    receiver_balance = serializers.IntegerField()
    gift_transaction_id = serializers.IntegerField()


class GiftTransactionSerializer(serializers.ModelSerializer):
    stream_id = serializers.IntegerField(source='stream.id', read_only=True)
    video_id = serializers.IntegerField(source='video.id', read_only=True)
    drama_series_id = serializers.IntegerField(source='drama_series.id', read_only=True)

    class Meta:
        model = GiftTransaction
        fields = (
            'id',
            'stream_id',
            'video_id',
            'drama_series_id',
            'target_type',
            'target_id',
            'payment_method',
            'amount',
            'gift_name_snapshot',
            'points_price_snapshot',
            'quantity',
            'total_points',
            'points_amount',
            'credits_amount',
            'created_at',
        )
