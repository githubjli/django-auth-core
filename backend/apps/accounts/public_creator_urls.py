from django.urls import path

from apps.accounts.views import PublicCreatorDetailAPIView, PublicCreatorVideoListAPIView

urlpatterns = [
    path('<int:creator_id>/', PublicCreatorDetailAPIView.as_view(), name='public-creator-detail'),
    path('<int:creator_id>/videos/', PublicCreatorVideoListAPIView.as_view(), name='public-creator-videos'),
]
