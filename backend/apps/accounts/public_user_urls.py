from django.urls import path

from apps.accounts.views import PublicUserDetailAPIView

urlpatterns = [
    path('<int:user_id>/', PublicUserDetailAPIView.as_view(), name='public-user-detail'),
]
