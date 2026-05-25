from django.urls import path

from apps.accounts.views import (
    PublicCreatorDetailAPIView,
    PublicCreatorDramaListAPIView,
    PublicCreatorLiveListAPIView,
    PublicCreatorVideoListAPIView,
)

urlpatterns = [
    path('<int:creator_id>/', PublicCreatorDetailAPIView.as_view(), name='public-creator-detail'),
    path('<int:creator_id>/videos/', PublicCreatorVideoListAPIView.as_view(), name='public-creator-videos'),
    path('<int:creator_id>/dramas/', PublicCreatorDramaListAPIView.as_view(), name='public-creator-dramas'),
    path('<int:creator_id>/lives/', PublicCreatorLiveListAPIView.as_view(), name='public-creator-lives'),
]
