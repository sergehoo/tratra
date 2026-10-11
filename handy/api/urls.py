# /Users/ogahserge/Documents/tratra/handy/api/urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from handy.api import cash as cash_api
from handy.api.addresses import geo_reverse, geo_search, me_address_detail, me_address_set_primary, me_addresses
from handy.api.recovery import password_reset_confirm, password_reset_request
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenBlacklistView

from .views import (
    UserViewSet, HandymanProfileViewSet, ServiceCategoryViewSet, ServiceViewSet, ServiceImageViewSet,
    BookingViewSet, PaymentViewSet, PaymentLogViewSet, PayoutViewSet, ReviewViewSet, ConversationViewSet,
    MessageViewSet, HandymanDocumentViewSet, ReportViewSet, DeviceViewSet, DisputeViewSet,
    TimeOffViewSet, SubscriptionPlanViewSet, SubscriptionViewSet,
    price_estimate, payment_initiate, match, PaymentWebhook, EmailOrUsernameTokenObtainPairView, HeroSlideViewSet,
    otp_request, otp_verify, coupon_validate, payout_account, company_profile, public_stats
)

from .notification_views import NotificationViewSet, me_marketing_consent, me_notification_preferences
from .dashboard import (
    me_become_provider, me_conversation_messages, me_conversations, me_dashboard,
    me_notifications_read_all, me_reviews, me_services,
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
router.register(r'payouts', PayoutViewSet, basename='payouts')
router.register(r'disputes', DisputeViewSet, basename='disputes')
router.register(r'timeoffs', TimeOffViewSet, basename='timeoffs')
router.register(r'subscription-plans', SubscriptionPlanViewSet, basename='subscription-plans')
router.register(r'subscriptions', SubscriptionViewSet, basename='subscriptions')
router.register(r'reviews', ReviewViewSet, basename='reviews')
router.register(r'conversations', ConversationViewSet, basename='conversations')
router.register(r'messages', MessageViewSet, basename='messages')
router.register(r'notifications', NotificationViewSet, basename='notifications')
router.register(r'handyman-docs', HandymanDocumentViewSet, basename='handyman-docs')
router.register(r'reports', ReportViewSet, basename='reports')
router.register(r'devices', DeviceViewSet, basename='devices')
router.register(r'slides', HeroSlideViewSet, basename='slides')
urlpatterns = [
    # ⚠️ Les routes explicites DOIVENT précéder le router : sinon
    # `payments/{pk}/` (route détail générée) masque `payments/initiate/`
    # et `payments/webhook/...` (résolus en pk="initiate"/"webhook" -> 405).
    path('auth/login/', EmailOrUsernameTokenObtainPairView.as_view(), name='jwt-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='jwt-refresh'),
    path('auth/logout/', TokenBlacklistView.as_view(), name='jwt-logout'),
    path('price/estimate/', price_estimate, name='price-estimate'),
    path('payments/initiate/', payment_initiate, name='payment-initiate'),
    path('payments/cash/<int:pk>/respond/', cash_api.cash_respond, name='cash-respond'),
    path('payments/cash/<int:pk>/receipt/', cash_api.cash_receipt, name='cash-receipt'),
    path('bookings/<int:pk>/payment/', cash_api.booking_payment, name='booking-payment'),
    path('bookings/<int:pk>/payment/cash/', cash_api.cash_declare, name='cash-declare'),
    path('payments/webhook/<str:provider>/', PaymentWebhook.as_view(), name='payment-webhook'),
    path('match/', match, name='match'),
    path('auth/otp/request/', otp_request, name='otp-request'),
    path('auth/otp/verify/', otp_verify, name='otp-verify'),
    path('auth/password-reset/request/', password_reset_request, name='password-reset-request'),
    path('auth/password-reset/confirm/', password_reset_confirm, name='password-reset-confirm'),
    path('coupons/validate/', coupon_validate, name='coupon-validate'),
    path('payout-account/', payout_account, name='payout-account'),
    path('companies/me/', company_profile, name='company-profile'),
    # Public (landing) : chiffres réels, sans authentification.
    path('public/stats/', public_stats, name='public-stats'),
    # Compte unifié : tableau de bord agrégé + création du profil professionnel du compte courant.
    path('me/dashboard/', me_dashboard, name='me-dashboard'),
    path('me/addresses/', me_addresses, name='me-addresses'),
    path('me/addresses/<int:pk>/', me_address_detail, name='me-address-detail'),
    path('me/addresses/<int:pk>/primary/', me_address_set_primary, name='me-address-primary'),
    path('geo/search/', geo_search, name='geo-search'),
    path('geo/reverse/', geo_reverse, name='geo-reverse'),
    path('me/handyman-profile/', me_become_provider, name='me-handyman-profile'),
    path('me/services/', me_services, name='me-services'),
    path('me/conversations/', me_conversations, name='me-conversations'),
    path('me/conversations/<int:pk>/messages/', me_conversation_messages, name='me-conversation-messages'),
    path('me/reviews/', me_reviews, name='me-reviews'),
    path('me/notifications/read-all/', me_notifications_read_all, name='me-notifications-read-all'),
    path('me/notification-preferences/', me_notification_preferences, name='me-notification-preferences'),
    path('me/marketing-consent/', me_marketing_consent, name='me-marketing-consent'),

    path('', include('trust.urls')),  # Tratra Trust / Tratra ID
    path('', include('live.urls')),   # Tratra Live : suivi en direct des missions
    path('', include('business.urls')),  # Tratra Business : organisations, interventions, budgets
    path('', include(router.urls)),
]