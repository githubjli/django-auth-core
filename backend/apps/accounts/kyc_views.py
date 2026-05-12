from django.utils import timezone
from rest_framework import generics, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.kyc_serializers import (
    KycDocumentSerializer,
    KycDocumentUploadSerializer,
    KycProfileSerializer,
    KycProfileUpsertSerializer,
)
from apps.accounts.models import KycDocument, KycProfile


class KycMeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = KycProfile.objects.prefetch_related('documents').filter(user=request.user).first()
        if profile is None:
            return Response(
                {
                    'status': KycProfile.STATUS_NOT_SUBMITTED,
                    'full_name': '',
                    'date_of_birth': None,
                    'nationality': '',
                    'id_type': '',
                    'id_number': '',
                    'id_expiry_date': None,
                    'submitted_at': None,
                    'reviewed_at': None,
                    'reject_reason': '',
                    'documents': {
                        KycDocument.TYPE_ID_FRONT: None,
                        KycDocument.TYPE_SELFIE: None,
                    },
                },
                status=status.HTTP_200_OK,
            )
        return Response(KycProfileSerializer(profile, context={'request': request}).data, status=status.HTTP_200_OK)

    def post(self, request):
        return self._upsert(request)

    def patch(self, request):
        return self._upsert(request)

    def _upsert(self, request):
        serializer = KycProfileUpsertSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        profile = serializer.save()
        profile = KycProfile.objects.prefetch_related('documents').get(pk=profile.pk)
        return Response(KycProfileSerializer(profile, context={'request': request}).data, status=status.HTTP_200_OK)


class KycDocumentUploadAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = KycDocumentUploadSerializer
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = self.get_serializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        document = serializer.save()
        return Response(KycDocumentSerializer(document, context={'request': request}).data, status=status.HTTP_200_OK)


class KycSubmitAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        profile, _created = KycProfile.objects.prefetch_related('documents').get_or_create(user=request.user)
        missing_fields = self._missing_required_fields(profile)
        if missing_fields:
            return Response({'detail': f'Missing required KYC fields: {", ".join(missing_fields)}.'}, status=status.HTTP_400_BAD_REQUEST)
        document_types = set(profile.documents.values_list('document_type', flat=True))
        required_documents = {KycDocument.TYPE_ID_FRONT, KycDocument.TYPE_SELFIE}
        if not required_documents.issubset(document_types):
            return Response({'detail': 'id_front and selfie are required.'}, status=status.HTTP_400_BAD_REQUEST)
        profile.status = KycProfile.STATUS_PENDING
        profile.submitted_at = timezone.now()
        profile.reviewed_at = None
        profile.reviewed_by = None
        profile.reject_reason = ''
        profile.save(update_fields=['status', 'submitted_at', 'reviewed_at', 'reviewed_by', 'reject_reason', 'updated_at'])
        profile = KycProfile.objects.prefetch_related('documents').get(pk=profile.pk)
        return Response(KycProfileSerializer(profile, context={'request': request}).data, status=status.HTTP_200_OK)

    def _missing_required_fields(self, profile):
        required = [
            'full_name',
            'date_of_birth',
            'nationality',
            'id_type',
            'id_number',
            'id_expiry_date',
        ]
        return [field for field in required if not getattr(profile, field)]
