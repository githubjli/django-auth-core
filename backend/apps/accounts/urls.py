from django.urls import path

from apps.accounts.views import LoginAPIView, MeAPIView, RefreshAPIView, RegisterAPIView

urlpatterns = [
    path('register', RegisterAPIView.as_view(), name='auth-register'),
    path('login', LoginAPIView.as_view(), name='auth-login'),
    path('refresh', RefreshAPIView.as_view(), name='auth-refresh'),
    path('me', MeAPIView.as_view(), name='auth-me'),
]
