from django.urls import path

from apps.accounts.kyc_views import KycDocumentUploadAPIView, KycMeAPIView, KycSubmitAPIView

urlpatterns = [
    path('me/', KycMeAPIView.as_view(), name='kyc-me'),
    path('documents/', KycDocumentUploadAPIView.as_view(), name='kyc-document-upload'),
    path('submit/', KycSubmitAPIView.as_view(), name='kyc-submit'),
]
