from django.utils import timezone
from rest_framework import serializers

from apps.accounts.models import KycDocument, KycProfile


class KycDocumentSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = KycDocument
        fields = (
            'document_type',
            'image_url',
            'uploaded_at',
        )
        read_only_fields = fields

    def get_image_url(self, obj):
        if not obj.image:
            return ''
        url = obj.image.url
        request = self.context.get('request')
        if request is not None:
            return request.build_absolute_uri(url)
        return url


class KycProfileSerializer(serializers.ModelSerializer):
    documents = serializers.SerializerMethodField()

    class Meta:
        model = KycProfile
        fields = (
            'status',
            'full_name',
            'date_of_birth',
            'nationality',
            'id_type',
            'id_number',
            'id_expiry_date',
            'submitted_at',
            'reviewed_at',
            'reject_reason',
            'documents',
        )
        read_only_fields = fields

    def get_documents(self, obj):
        documents = {KycDocument.TYPE_ID_FRONT: None, KycDocument.TYPE_SELFIE: None}
        for document in obj.documents.all():
            documents[document.document_type] = KycDocumentSerializer(document, context=self.context).data
        return documents


class KycProfileUpsertSerializer(serializers.Serializer):
    full_name = serializers.CharField(max_length=255)
    date_of_birth = serializers.DateField()
    nationality = serializers.CharField(max_length=8)
    id_type = serializers.ChoiceField(choices=KycProfile.ID_TYPE_CHOICES)
    id_number = serializers.CharField(max_length=128)
    id_expiry_date = serializers.DateField()

    def validate_full_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('full_name is required.')
        return value

    def validate_nationality(self, value):
        value = value.strip().upper()
        if not value:
            raise serializers.ValidationError('nationality is required.')
        return value

    def validate_id_number(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError('id_number is required.')
        return value

    def save(self, **kwargs):
        user = self.context['request'].user
        profile, _created = KycProfile.objects.get_or_create(user=user)
        for field, value in self.validated_data.items():
            setattr(profile, field, value)
        profile.status = KycProfile.STATUS_PENDING
        profile.submitted_at = timezone.now()
        profile.reviewed_at = None
        profile.reviewed_by = None
        profile.reject_reason = ''
        profile.save(
            update_fields=[
                'full_name',
                'date_of_birth',
                'nationality',
                'id_type',
                'id_number',
                'id_expiry_date',
                'status',
                'submitted_at',
                'reviewed_at',
                'reviewed_by',
                'reject_reason',
                'updated_at',
            ]
        )
        return profile


class KycDocumentUploadSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=KycDocument.DOCUMENT_TYPE_CHOICES)
    image = serializers.FileField()

    def save(self, **kwargs):
        user = self.context['request'].user
        profile, _created = KycProfile.objects.get_or_create(user=user)
        document, _created = KycDocument.objects.update_or_create(
            kyc_profile=profile,
            document_type=self.validated_data['document_type'],
            defaults={
                'user': user,
                'image': self.validated_data['image'],
            },
        )
        if profile.status == KycProfile.STATUS_APPROVED:
            profile.status = KycProfile.STATUS_PENDING
            profile.submitted_at = timezone.now()
            profile.reviewed_at = None
            profile.reviewed_by = None
            profile.reject_reason = ''
            profile.save(update_fields=['status', 'submitted_at', 'reviewed_at', 'reviewed_by', 'reject_reason', 'updated_at'])
        return document
