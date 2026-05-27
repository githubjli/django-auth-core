from django.urls import path

from apps.accounts.views import CartCountAPIView, CartItemDeleteAPIView, CartItemListCreateAPIView

urlpatterns = [
    path('items/', CartItemListCreateAPIView.as_view(), name='cart-item-list-create'),
    path('items/<int:id>/', CartItemDeleteAPIView.as_view(), name='cart-item-delete'),
    path('count/', CartCountAPIView.as_view(), name='cart-count'),
]
