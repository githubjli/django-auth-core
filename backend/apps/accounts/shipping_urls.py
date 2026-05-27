from django.urls import path

from apps.accounts.views import ShippingAddressDetailAPIView, ShippingAddressListCreateAPIView

urlpatterns = [
    path('shipping-addresses/', ShippingAddressListCreateAPIView.as_view(), name='shipping-address-list-create'),
    path('shipping-addresses/<int:id>/', ShippingAddressDetailAPIView.as_view(), name='shipping-address-detail'),
]
