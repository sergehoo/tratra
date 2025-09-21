# /Users/ogahserge/Documents/tratra/handy/api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenBlacklistView

from .views import (
    UserViewSet, HandymanProfileViewSet, ServiceCategoryViewSet, ServiceViewSet, ServiceImageViewSet,
    BookingViewSet, PaymentViewSet, PaymentLogViewSet, ReviewViewSet, ConversationViewSet, MessageViewSet,
    NotificationViewSet, HandymanDocumentViewSet, ReportViewSet, DeviceViewSet,
    price_estimate, payment_initiate, match, PaymentWebhook
)

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='users')
router.register(r'handymen', HandymanProfileViewSet, basename='handymen')
router.register(r'categories', ServiceCategoryViewSet, basename='categories')
router.register(r'services', ServiceViewSet, basename='services')
router.register(r'service-images', ServiceImageViewSet, basename='service-images')
router.register(r'bookings', BookingViewSet, basename='bookings')
router.register(r'payments', PaymentViewSet, basename='payments')
router.register(r'payment-logs', PaymentLogViewSet, basename='payment-logs')
router.register(r'reviews', ReviewViewSet, basename='reviews')
router.register(r'conversations', ConversationViewSet, basename='conversations')
router.register(r'messages', MessageViewSet, basename='messages')
router.register(r'notifications', NotificationViewSet, basename='notifications')
router.register(r'handyman-docs', HandymanDocumentViewSet, basename='handyman-docs')
router.register(r'reports', ReportViewSet, basename='reports')
router.register(r'devices', DeviceViewSet, basename='devices')

urlpatterns = [
    path('', include(router.urls)),
    path('auth/login/', TokenObtainPairView.as_view(), name='jwt-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='jwt-refresh'),
    path('auth/logout/', TokenBlacklistView.as_view(), name='jwt-logout'),
    path('price/estimate/', price_estimate, name='price-estimate'),
    path('payments/initiate/', payment_initiate, name='payment-initiate'),
    path('payments/webhook/<str:provider>/', PaymentWebhook.as_view(), name='payment-webhook'),
    path('match/', match, name='match'),
]