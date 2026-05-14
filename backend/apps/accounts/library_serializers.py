from rest_framework import serializers


class LibraryUserSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField(allow_blank=True, allow_null=True)


class LibraryContentSerializer(serializers.Serializer):
    type = serializers.CharField(allow_blank=True, allow_null=True)
    id = serializers.IntegerField(allow_null=True)
    title = serializers.CharField(allow_blank=True, allow_null=True)


class LibraryHistoryItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=('drama', 'video'))
    id = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    cover_url = serializers.CharField(allow_null=True, required=False)
    thumbnail_url = serializers.CharField(allow_null=True, required=False)
    series_id = serializers.IntegerField(allow_null=True, required=False)
    episode_id = serializers.IntegerField(allow_null=True, required=False)
    episode_no = serializers.IntegerField(allow_null=True, required=False)
    progress_seconds = serializers.IntegerField()
    duration_seconds = serializers.IntegerField()
    updated_at = serializers.DateTimeField()


class LibraryLikedItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=('video',))
    id = serializers.IntegerField()
    title = serializers.CharField(allow_blank=True)
    thumbnail_url = serializers.CharField(allow_null=True)
    liked_at = serializers.DateTimeField()


class LibraryPurchasedItemSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=('drama_episode', 'order', 'membership'))
    id = serializers.IntegerField()
    series_id = serializers.IntegerField(allow_null=True, required=False)
    title = serializers.CharField(allow_blank=True)
    cover_url = serializers.CharField(allow_null=True, required=False)
    source = serializers.CharField(allow_blank=True, required=False)
    payment_method = serializers.CharField(allow_blank=True, required=False)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    currency = serializers.CharField(allow_blank=True, required=False)
    status = serializers.CharField(allow_blank=True, required=False)
    starts_at = serializers.DateTimeField(allow_null=True, required=False)
    ends_at = serializers.DateTimeField(allow_null=True, required=False)
    purchased_at = serializers.DateTimeField()


class LibraryGiftItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    direction = serializers.ChoiceField(choices=('sent', 'received'))
    gift_name = serializers.CharField(allow_blank=True)
    amount = serializers.IntegerField()
    points_amount = serializers.IntegerField()
    credits_amount = serializers.IntegerField()
    sender = LibraryUserSerializer(required=False)
    receiver = LibraryUserSerializer(required=False)
    content = LibraryContentSerializer()
    created_at = serializers.DateTimeField()
