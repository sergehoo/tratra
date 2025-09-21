# /Users/ogahserge/Documents/tratra/tratra/urls.py
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include

from handy.api.urls import router
from handy.views import Landing, HomePageView, HandymanDashboardView, BookingCreateView, EmployerSignupView, \
    HandymanSignupView, CustomLoginView, EmployeurDashboardView, HandymanProfileUpdateView, HandymanProfileDetailView, \
    ServiceCreateView, ServiceUpdateView, ServiceStatsView, HandymanCalendarView, ServiceSearchView, ServiceDetailView, \
    WorkerProfileView, MyBookingsListView, CreateBookingView, BookingRespondView, BookingDetailView, SendMessageView, \
    AddReviewView, AddPaymentView, HandymanBookingDetailView, BookingStartView, BookingCompleteView, BookingCancelView, \
    DepositTopUpView

urlpatterns = [
                  # path("__reload__/", include("django_browser_reload.urls")),
                  path("healthz", lambda r: HttpResponse("ok")),
                  path('admin/', admin.site.urls),
                  path('accounts/', include('allauth.urls')),
                  path('handy/', include('handy.api.urls')),
                  path('', Landing.as_view(), name='landing'),
                  path('home', HomePageView.as_view(), name='home'),

                  path('accounts/signup/employeur/', EmployerSignupView.as_view(), name='employer_signup'),
                  path('accounts/signup/artisan/', HandymanSignupView.as_view(), name='handyman_signup'),

                  path('artisan/dashboard/', HandymanDashboardView.as_view(), name='handydash'),
                  path("artisan/profile/update/", HandymanProfileUpdateView.as_view(), name="handyman_profile_update"),
                  path("artisan/profile/details/<int:pk>", HandymanProfileDetailView.as_view(),
                       name="handyman_profile_detail"),
                  path('calendar/', HandymanCalendarView.as_view(), name='handyman_calendar'),

                  path('employeur/dashboard/', EmployeurDashboardView.as_view(), name='employeur_dashboard'),

                  path('booking/create/', BookingCreateView.as_view(), name='booking_create'),
                  path('account/login/', CustomLoginView.as_view(), name='account_login'),

                  path('services/create/', ServiceCreateView.as_view(), name='service_create'),
                  path('services/<int:pk>/update/', ServiceUpdateView.as_view(), name='service_update'),
                  path('services/<int:pk>/stats/', ServiceStatsView.as_view(), name='service_stats'),
                  path('service/<int:service_id>/', ServiceDetailView.as_view(), name='service_detail'),

                  path('worker/<int:worker_id>/', WorkerProfileView.as_view(), name='worker_profile'),
                  path('my-bookings/', MyBookingsListView.as_view(), name='my_bookings'),

                  path('service/<int:service_id>/book/', CreateBookingView.as_view(), name='create_booking'),
                  path('booking/<int:booking_id>/respond/', BookingRespondView.as_view(), name='booking_respond'),

                  path('services/', ServiceSearchView.as_view(), name='service_search'),
                  path('handyman/booking/<int:booking_id>/', HandymanBookingDetailView.as_view(),
                       name='handy_booking_detail'),
                  path('booking/<int:booking_id>/start/', BookingStartView.as_view(), name='booking_start'),
                  path('booking/<int:booking_id>/complete/', BookingCompleteView.as_view(), name='booking_complete'),
                  path('booking/<int:booking_id>/cancel/', BookingCancelView.as_view(), name='booking_cancel'),
                  path('booking/<int:booking_id>/', BookingDetailView.as_view(), name='booking_detail'),
                  path('booking/<int:booking_id>/send-message/', SendMessageView.as_view(), name='send_message'),
                  path('booking/<int:booking_id>/add-review/', AddReviewView.as_view(), name='add_review'),
                  path('booking/<int:booking_id>/add-payment/', AddPaymentView.as_view(), name='add_payment'),
                  path('artisan/deposit/topup/', DepositTopUpView.as_view(), name='deposit_topup'),
              ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
