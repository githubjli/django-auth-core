from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from apps.accounts.drama_views import DramaSeriesPagination
from apps.accounts.meow_points_serializers import (
    MeowPointLedgerSerializer,
    MeowPointPackageSerializer,
    MeowPointWalletSerializer,
)
from apps.accounts.models import MeowPointLedger, MeowPointPackage
from apps.accounts.services import MeowPointService


class MeowPointWalletAPIView(generics.RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowPointWalletSerializer

    def get_object(self):
        return MeowPointService.get_or_create_wallet(self.request.user)


class MeowPointPackageListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowPointPackageSerializer

    def get_queryset(self):
        return MeowPointPackage.objects.filter(status=MeowPointPackage.STATUS_ACTIVE).order_by('sort_order', 'id')


class MeowPointLedgerListAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = MeowPointLedgerSerializer
    pagination_class = DramaSeriesPagination

    def get_queryset(self):
        return MeowPointLedger.objects.filter(user=self.request.user).order_by('-created_at', '-id')
