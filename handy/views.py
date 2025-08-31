import calendar
import json
import logging
from datetime import timedelta, datetime
from decimal import Decimal

from allauth.account.views import SignupView, LoginView
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum, Max, Count, Avg, Min, Q, F, Prefetch
from django.db.models.functions import TruncDay
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.views.generic import TemplateView, DetailView, ListView, CreateView, UpdateView, View
from handy.forms import HandymanSignupForm, EmployerSignupForm, HandymanProfileForm, ServiceImageFormSet, ServiceForm, \
    BookingForm, BookingResponseForm, MessageForm, ReviewForm, PaymentForm, DepositTopUpForm
from handy.models import HandymanProfile, Service, Booking, ServiceCategory, Review, Payment, Notification, Message, \
    Conversation, DepositTransaction

from django.contrib.auth import get_user_model

User = get_user_model()
logger = logging.getLogger(__name__)


# Create your views here.

class Landing(TemplateView):
    template_name = "landing/landing.html"


class HomePageView(LoginRequiredMixin, TemplateView):
    login_url = '/accounts/login/'
    # form_class = LoginForm
    template_name = "admin/home.html"


class EmployerSignupView(SignupView):
    template_name = "allauth/account/employer_signup.html"
    form_class = EmployerSignupForm


class HandymanSignupView(SignupView):
    template_name = "allauth/account/handyman_signup.html"
    form_class = HandymanSignupForm


class CustomLoginView(LoginView):
    template_name = "allauth/account/login.html"


class HandymanDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "handyman/dashboard.html"

    def test_func(self):
        return self.request.user.user_type == "handyman"

    def handle_no_permission(self):
        if self.request.user.is_authenticated and self.request.user.user_type == "employeur":
            return redirect(reverse_lazy("employeur_dashboard"))
        return super().handle_no_permission()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        handyman = self.request.user
        profile = handyman.handyman_profile
        user = self.request.user
        now = timezone.now()

        # Missions aujourd'hui
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        today_missions = Booking.objects.filter(
            handyman=user,
            booking_date__gte=today_start,
            booking_date__lte=today_end,
            status__in=['confirmed', 'in_progress']
        )

        # Missions aujourd'hui
        today = timezone.now().date()
        missions_today = Booking.objects.filter(
            handyman=handyman,
            booking_date__date=today,
            status__in=["pending", "confirmed", "in_progress"]
        )
        mission_count = missions_today.count()
        next_service = missions_today.order_by('booking_date').first()
        if next_service:
            delta = next_service.booking_date - timezone.now()
            next_service_in = int(delta.total_seconds() // 3600)
        else:
            next_service_in = None

        # Dispos ouvertes = clé `availability` (exemple)
        total_slots = sum(1 for day, slots in profile.availability.items() if slots)

        # Réservations à venir (dans les 7 prochains jours)
        upcoming_bookings = Booking.objects.filter(
            handyman=user,
            booking_date__gte=timezone.now(),
            booking_date__lte=timezone.now() + timedelta(days=7),
            status__in=['confirmed', 'in_progress']
        ).order_by('booking_date')

        # Demandes récentes (en attente, créées dans les 3 derniers jours)
        booking_requests = Booking.objects.filter(
            handyman=user,
            status='pending',
            created_at__gte=timezone.now() - timedelta(days=3)
        ).order_by('-created_at')

        # Historique des missions (terminées ou annulées)
        completed_bookings = Booking.objects.filter(
            handyman=user,
            status__in=['completed', 'cancelled']
        ).order_by('-booking_date')[:10]  # Limite à 10 résultats

        # Prochaine mission
        next_mission = Booking.objects.filter(
            handyman=user,
            booking_date__gt=now,
            status='confirmed'
        ).order_by('booking_date').first()

        # Statistiques mensuelles
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        # Missions du mois
        monthly_bookings = Booking.objects.filter(
            handyman=user,
            booking_date__gte=month_start,
            booking_date__lte=month_end
        )

        # Revenu mensuel
        revenue = monthly_bookings.filter(
            payment__is_paid=True
        ).aggregate(total=Sum('payment__amount'))['total'] or 0

        # Nombre de missions
        total_missions = monthly_bookings.count()

        # Croissance par rapport au mois dernier
        last_month_start = (month_start - timedelta(days=1)).replace(day=1)
        last_month_end = month_start - timedelta(days=1)
        last_month_missions = Booking.objects.filter(
            handyman=user,
            booking_date__gte=last_month_start,
            booking_date__lte=last_month_end
        ).count()

        mission_growth = 0
        if last_month_missions > 0:
            mission_growth = round((total_missions - last_month_missions) / last_month_missions * 100)

        # Graphique des revenus par jour
        revenue_data = monthly_bookings.filter(
            payment__is_paid=True
        ).annotate(day=TruncDay('booking_date')).values('day').annotate(
            total=Sum('payment__amount')
        ).order_by('day')

        max_revenue = revenue_data.aggregate(max=Max('total'))['max'] or 1
        revenue_chart = []
        for entry in revenue_data:
            percentage = min(100, round(entry['total'] / max_revenue * 100))
            revenue_chart.append({
                'day': entry['day'],
                'amount': entry['total'],
                'percentage': percentage
            })

        # Disponibilités
        availability = user.handyman_profile.availability or {}
        availability_slots = sum(len(slots) for slots in availability.values() if slots)

        # Pourcentage de disponibilité (exemple)
        days_in_month = (month_end - month_start).days + 1
        availability_percentage = min(100, round(availability_slots / (days_in_month * 3) * 100))

        # Calcule la balance réelle de la caution
        transactions = DepositTransaction.objects.filter(
            handyman=self.request.user,
            status='completed'
        )
        deposit_balance = transactions.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        # Définir un seuil minimal recommandé (ex. 50 000 FCFA)
        deposit_threshold = Decimal('50000.00')

        # Pourcentage par rapport au seuil
        deposit_percentage = min(100,
                                 round((deposit_balance / deposit_threshold) * 100)) if deposit_threshold > 0 else 0

        context.update({
            'deposit_balance': deposit_balance,
            'deposit_threshold': deposit_threshold,
            'deposit_percentage': deposit_percentage,
            "handyman_name": handyman.get_full_name() or handyman.email,
            "bio": profile.bio or "Professionnel multiservice",
            "rating": profile.rating,
            "completed_jobs": profile.completed_jobs,
            "is_verified": handyman.is_verified,
            "is_completed": handyman.handyman_profile.is_fully_completed,
            "valeur_completed": handyman.handyman_profile.profile_completion(),
            "is_premium": profile.is_approved,
            "total_slots": total_slots,
            "profile_picture": profile.photo.url if profile.photo else None,
            "mission_count": mission_count,
            "next_service_in": next_service_in,
            'services': self.request.user.services.all(),
            'upcoming_bookings': upcoming_bookings,
            'booking_requests': booking_requests,
            'completed_bookings': completed_bookings,
            'today_missions_count': today_missions.count(),
            'next_mission': next_mission,
            'monthly_stats': {
                'total_missions': total_missions,
                'revenue': revenue,
                'mission_growth': mission_growth,
                'revenue_chart': revenue_chart,
                'availability_percentage': availability_percentage,
                'availability_slots': availability_slots,
            }
        }
        )
        return context


class HandymanCalendarView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "handyman/calendar.html"

    def test_func(self):
        return self.request.user.user_type == "handyman"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Récupérer les réservations
        bookings = Booking.objects.filter(
            handyman=user,
            booking_date__gte=timezone.now() - timedelta(days=30),
            booking_date__lte=timezone.now() + timedelta(days=60)
        ).order_by('booking_date')

        # Formater les réservations pour FullCalendar
        formatted_bookings = []
        for booking in bookings:
            formatted_bookings.append({
                'id': booking.id,
                'title': f"{booking.service.title} - {booking.client.get_full_name()}" if booking.service else f"Réservation - {booking.client.get_full_name()}",
                'start': booking.booking_date.isoformat(),
                'end': booking.end_date.isoformat() if booking.end_date else (
                        booking.booking_date + timedelta(hours=2)).isoformat(),
                'color': self.get_status_color(booking.status),
                'extendedProps': {
                    'status': booking.get_status_display(),
                    'client': booking.client.get_full_name(),
                    'address': f"{booking.address}, {booking.city}",
                    'description': booking.description or "Aucune description",
                }
            })

        # Récupérer les disponibilités
        handyman_profile = HandymanProfile.objects.get(user=user)
        availability = handyman_profile.availability or {}

        # Formater les disponibilités pour FullCalendar
        formatted_availability = []
        today = timezone.now().date()

        # Générer les disponibilités pour les 60 prochains jours
        for day_offset in range(0, 60):
            current_date = today + timedelta(days=day_offset)
            day_name = calendar.day_name[current_date.weekday()].lower()

            if day_name in availability and availability[day_name]:
                for slot in availability[day_name]:
                    start_hour, start_minute = slot[0], 0
                    end_hour, end_minute = slot[1], 0

                    start_time = datetime(
                        current_date.year, current_date.month, current_date.day,
                        start_hour, start_minute, tzinfo=timezone.utc
                    )

                    end_time = datetime(
                        current_date.year, current_date.month, current_date.day,
                        end_hour, end_minute, tzinfo=timezone.utc
                    )

                    formatted_availability.append({
                        'title': 'Disponible',
                        'start': start_time.isoformat(),
                        'end': end_time.isoformat(),
                        'color': '#10B981',
                        'textColor': '#ffffff',
                        'display': 'background',
                        'extendedProps': {
                            'type': 'availability'
                        }
                    })

        context.update({
            'bookings': json.dumps(formatted_bookings),
            'availability': json.dumps(formatted_availability),
            'today': timezone.now().isoformat(),
        })
        return context

    def get_status_color(self, status):
        colors = {
            'pending': '#FBBF24',  # Jaune
            'confirmed': '#10B981',  # Vert
            'in_progress': '#3B82F6',  # Bleu
            'completed': '#6B7280',  # Gris
            'cancelled': '#EF4444',  # Rouge
        }
        return colors.get(status, '#6B7280')


class HandymanProfileDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = HandymanProfile
    template_name = "handyman/profile_detail.html"

    def get_object(self, queryset=None):
        return self.request.user.handyman_profile

    def test_func(self):
        return self.request.user.user_type == "handyman"

    def handle_no_permission(self):
        return redirect("employeur_dashboard")


class DepositTopUpView(LoginRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        form = DepositTopUpForm(request.POST)
        if form.is_valid():
            amount = form.cleaned_data['amount']

            with transaction.atomic():
                DepositTransaction.objects.create(
                    handyman=request.user,
                    type='deposit',
                    amount=amount,
                    status='completed'
                )
            messages.success(request, f"Caution rechargée de {amount} FCFA avec succès.")
        else:
            messages.error(request, "Montant invalide ou trop faible.")
        return redirect('handydash')

    def get(self, request, *args, **kwargs):
        form = DepositTopUpForm()
        return render(request, 'handyman/deposit_topup.html', {'form': form})


class HandymanProfileUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = HandymanProfile
    form_class = HandymanProfileForm
    template_name = "handyman/profile_update.html"
    success_url = reverse_lazy("handydash")

    def form_valid(self, form):
        logger.info(f"FICHIER RECU : {self.request.FILES}")

        try:
            return super().form_valid(form)
        except Exception as e:
            logger.error(f"Erreur de sauvegarde du profil: {str(e)}", exc_info=True)
            messages.error(
                self.request,
                "Une erreur s'est produite lors de la sauvegarde. Veuillez réessayer."
            )
            return self.form_invalid(form)

    def form_invalid(self, form):
        logger.info(f"FICHIER RECU : {self.request.FILES}")

        logger.warning(
            f"Form invalide pour l'utilisateur {self.request.user.pk}: "
            f"Erreurs: {form.errors.as_data()}"
        )
        messages.error(self.request, "Veuillez corriger les erreurs du formulaire avant de soumettre.")
        return super().form_invalid(form)

    def get_object(self, queryset=None):
        return self.request.user.handyman_profile

    def test_func(self):
        return self.request.user.user_type == "handyman"

    def handle_no_permission(self):
        return redirect("employeur_dashboard")


class HandymanBookingDetailView(LoginRequiredMixin, DetailView):
    model = Booking
    template_name = 'handyman/booking_detail.html'
    context_object_name = 'booking'
    pk_url_kwarg = 'booking_id'

    def get_queryset(self):
        return Booking.objects.select_related(
            'service', 'client', 'handyman', 'service__category'
        ).prefetch_related(
            Prefetch('conversation__messages', queryset=Message.objects.select_related('sender'))
        )

    def get_object(self, queryset=None):
        booking = super().get_object(queryset)
        # Vérifier que l'utilisateur a le droit d'accéder à cette réservation
        if self.request.user != booking.client and self.request.user != booking.handyman:
            raise PermissionDenied("Vous n'avez pas accès à cette réservation")
        return booking

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        booking = self.object

        # Formulaire de message
        context['message_form'] = MessageForm()

        # Formulaire d'avis (si la réservation est terminée)
        if booking.status == 'completed':
            try:
                # Vérifier s'il y a déjà un avis
                context['review'] = booking.review
            except:
                # Créer un formulaire d'avis si aucun avis n'existe
                context['review_form'] = ReviewForm()

        # Information de paiement
        try:
            context['payment'] = booking.payment
        except:
            # Si pas de paiement et que l'utilisateur est le prestataire
            if self.request.user == booking.handyman and booking.status == 'completed':
                context['payment_form'] = PaymentForm()

        # Actions disponibles selon le statut et l'utilisateur
        context['available_actions'] = self.get_available_actions(booking)

        return context

    def get_available_actions(self, booking):
        actions = []
        user = self.request.user

        if user == booking.client:
            # Actions pour le client
            if booking.status == 'pending':
                actions.append({
                    'name': 'Annuler la demande',
                    'url': reverse('booking_cancel', args=[booking.id]),
                    'class': 'bg-red-100 text-red-800 hover:bg-red-200'
                })
            elif booking.status == 'confirmed':
                actions.append({
                    'name': 'Confirmer le début',
                    'url': reverse('booking_start', args=[booking.id]),
                    'class': 'bg-green-100 text-green-800 hover:bg-green-200'
                })
                actions.append({
                    'name': 'Annuler la réservation',
                    'url': reverse('booking_cancel', args=[booking.id]),
                    'class': 'bg-red-100 text-red-800 hover:bg-red-200'
                })
            elif booking.status == 'in_progress':
                actions.append({
                    'name': 'Marquer comme terminé',
                    'url': reverse('booking_complete', args=[booking.id]),
                    'class': 'bg-green-100 text-green-800 hover:bg-green-200'
                })

        elif user == booking.handyman:
            # Actions pour le prestataire
            if booking.status == 'pending':
                actions.append({
                    'name': 'Répondre à la demande',
                    'url': reverse('booking_respond', args=[booking.id]),
                    'class': 'bg-blue-100 text-blue-800 hover:bg-blue-200'
                })
            elif booking.status == 'confirmed':
                actions.append({
                    'name': 'Commencer le service ',
                    'url': reverse('booking_start', args=[booking.id]),
                    'class': 'bg-green-100 text-green-800 hover:bg-green-200'
                })
                actions.append({
                    'name': 'Annuler la réservation',
                    'url': reverse('booking_cancel', args=[booking.id]),
                    'class': 'bg-red-100 text-red-800 hover:bg-red-200'
                })
            elif booking.status == 'in_progress':
                actions.append({
                    'name': 'Terminer le service',
                    'url': reverse('booking_complete', args=[booking.id]),
                    'class': 'bg-green-100 text-green-800 hover:bg-green-200'
                })

        return actions


class EmployeurDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "employeur/employee_dashboard.html"

    def test_func(self):
        return self.request.user.user_type == "employeur"

    def handle_no_permission(self):
        if self.request.user.is_authenticated and self.request.user.user_type == "handyman":
            return redirect(reverse_lazy("handydash"))
        return super().handle_no_permission()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        current_month = timezone.now().month

        # Statistiques principales
        stats = {
            'total_services': Service.objects.filter(is_active=True).count(),
            'monthly_spending': Payment.objects.filter(
                booking__client=user,
                payment_date__month=current_month
            ).aggregate(total=Sum('amount'))['total'] or 0,
            'pending_requests': Booking.objects.filter(
                client=user,
                status='pending'
            ).count(),
        }

        # Taux de réponse (basé sur les devis reçus)
        total_requests = Booking.objects.filter(client=user).count()
        # Compter les demandes avec au moins un devis
        responded_requests = Booking.objects.filter(
            client=user,
            quotations__isnull=False
        ).distinct().count()
        response_rate = round((responded_requests / total_requests * 100) if total_requests > 0 else 85)

        # Satisfaction
        employer_reviews = Review.objects.filter(booking__client=user)
        avg_rating = employer_reviews.aggregate(avg=Avg('rating'))['avg'] or 4.8
        review_count = employer_reviews.count()

        # Catégories populaires
        popular_categories = ServiceCategory.objects.annotate(
            provider_count=Count('services__handyman', distinct=True)
        ).order_by('-provider_count')[:4]

        # Prestataires recommandés
        recommended_workers = User.objects.filter(
            user_type='handyman',
            services__is_active=True
        ).annotate(
            avg_rating=Avg('handyman_bookings__review__rating'),
            review_count=Count('handyman_bookings__review')
        ).order_by('-avg_rating')[:4]

        # Demandes actives
        active_bookings = Booking.objects.filter(
            client=user,
            status__in=['pending', 'confirmed', 'in_progress']
        ).annotate(
            interested_count=Count('quotations')
        ).order_by('-created_at')[:3]

        # Services à venir
        upcoming_bookings = Booking.objects.filter(
            client=user,
            booking_date__gte=timezone.now(),
            status__in=['confirmed', 'in_progress']
        ).order_by('booking_date')[:3]

        # Calcul des dépenses quotidiennes réelles
        daily_spending = []
        today = timezone.now().date()
        for i in range(7):
            date = today - timedelta(days=i)
            daily_total = Payment.objects.filter(
                booking__client=user,
                payment_date__date=date
            ).aggregate(total=Sum('amount'))['total'] or 0
            daily_spending.append(float(daily_total))

        daily_spending.reverse()  # Pour avoir du plus ancien au plus récent
        max_daily = max(daily_spending) if daily_spending else 1

        context.update({
            'stats': stats,
            'response_rate': response_rate,
            'avg_rating': avg_rating,
            'review_count': review_count,
            'popular_categories': popular_categories,
            'recommended_workers': recommended_workers,
            'active_bookings': active_bookings,
            'upcoming_bookings': upcoming_bookings,
            'daily_spending': daily_spending,
            'max_daily_spending': max_daily,
        })
        return context


class BookingDetailView(LoginRequiredMixin, DetailView):
    model = Booking
    template_name = 'employeur/booking_detail.html'
    context_object_name = 'booking'
    pk_url_kwarg = 'booking_id'

    def get_queryset(self):
        return Booking.objects.select_related(
            'service', 'client', 'handyman', 'service__category'
        ).prefetch_related(
            Prefetch('conversation__messages', queryset=Message.objects.select_related('sender'))
        )

    def get_object(self, queryset=None):
        booking = super().get_object(queryset)
        # Vérifier que l'utilisateur a le droit d'accéder à cette réservation
        if self.request.user != booking.client and self.request.user != booking.handyman:
            raise PermissionDenied("Vous n'avez pas accès à cette réservation")
        return booking

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        booking = self.object

        # Formulaire de message
        context['message_form'] = MessageForm()

        # Formulaire d'avis (si la réservation est terminée)
        if booking.status == 'completed':
            try:
                # Vérifier s'il y a déjà un avis
                context['review'] = booking.review
            except:
                # Créer un formulaire d'avis si aucun avis n'existe
                context['review_form'] = ReviewForm()

        # Information de paiement
        try:
            context['payment'] = booking.payment
        except:
            # Si pas de paiement et que l'utilisateur est le prestataire
            if self.request.user == booking.handyman and booking.status == 'completed':
                context['payment_form'] = PaymentForm()

        # Actions disponibles selon le statut et l'utilisateur
        context['available_actions'] = self.get_available_actions(booking)

        return context

    def get_available_actions(self, booking):
        actions = []
        user = self.request.user

        if user == booking.client:
            # Actions pour le client
            if booking.status == 'pending':
                actions.append({
                    'name': 'Annuler la demande',
                    'url': reverse('booking_cancel', args=[booking.id]),
                    'method': 'post',
                    'class': 'bg-red-100 text-red-800 hover:bg-red-200'
                })
            elif booking.status == 'confirmed':
                actions.append({
                    'name': 'Confirmer le début',
                    'url': reverse('booking_start', args=[booking.id]),
                    'method': 'post',
                    'class': 'bg-green-100 text-green-800 hover:bg-green-200'
                })
                actions.append({
                    'name': 'Annuler la réservation',
                    'url': reverse('booking_cancel', args=[booking.id]),
                    'method': 'post',
                    'class': 'bg-red-100 text-red-800 hover:bg-red-200'
                })
            elif booking.status == 'in_progress':
                actions.append({
                    'name': 'Marquer comme terminé',
                    'url': reverse('booking_complete', args=[booking.id]),
                    'method': 'post',
                    'class': 'bg-green-100 text-green-800 hover:bg-green-200'
                })

        elif user == booking.handyman:
            # Actions pour le prestataire
            if booking.status == 'pending':
                actions.append({
                    'name': 'Répondre à la demande',
                    'url': reverse('booking_respond', args=[booking.id]),
                    'class': 'bg-blue-100 text-blue-800 hover:bg-blue-200'
                })
            elif booking.status == 'confirmed':
                actions.append({
                    'name': 'Commencer le service',
                    'url': reverse('booking_start', args=[booking.id]),
                    'class': 'bg-green-100 text-green-800 hover:bg-green-200'
                })
                actions.append({
                    'name': 'Annuler la réservation',
                    'url': reverse('booking_cancel', args=[booking.id]),
                    'class': 'bg-red-100 text-red-800 hover:bg-red-200'
                })
            elif booking.status == 'in_progress':
                actions.append({
                    'name': 'Terminer le service',
                    'url': reverse('booking_complete', args=[booking.id]),
                    'class': 'bg-green-100 text-green-800 hover:bg-green-200'
                })

        return actions


class SendMessageView(LoginRequiredMixin, CreateView):
    form_class = MessageForm
    http_method_names = ['post']

    def form_valid(self, form):
        booking = get_object_or_404(Booking, id=self.kwargs['booking_id'])

        # Créer ou récupérer la conversation
        conversation, created = Conversation.objects.get_or_create(
            booking=booking,
            defaults={}
        )

        # Créer le message
        message = form.save(commit=False)
        message.conversation = conversation
        message.sender = self.request.user
        message.save()

        # Mettre à jour la date de la conversation
        conversation.save()

        # Créer une notification pour l'autre partie
        recipient = booking.client if self.request.user == booking.handyman else booking.handyman
        Notification.objects.create(
            user=recipient,
            notification_type='message_received',
            message=f"Nouveau message concernant la réservation #{booking.id}",
            related_id=booking.id
        )

        messages.success(self.request, "Message envoyé avec succès")
        return super().form_valid(form)

    def get_success_url(self):
        booking_id = self.kwargs['booking_id']

        if self.request.user.user_type == 'handyman':
            return reverse('handy_booking_detail', args=[booking_id])
        else:
            return reverse('booking_detail', args=[booking_id])


class AddReviewView(LoginRequiredMixin, CreateView):
    form_class = ReviewForm
    http_method_names = ['post']

    def form_valid(self, form):
        booking = get_object_or_404(Booking, id=self.kwargs['booking_id'])

        # Vérifier que l'utilisateur est le client et que la réservation est terminée
        if self.request.user != booking.client or booking.status != 'completed':
            return PermissionDenied("Action non autorisée")

        # Créer l'avis
        review = form.save(commit=False)
        review.booking = booking
        review.save()

        messages.success(self.request, "Votre avis a été publié avec succès")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('booking_detail', args=[self.kwargs['booking_id']])


# class AddPaymentView(LoginRequiredMixin, CreateView):
#     form_class = PaymentForm
#     http_method_names = ['post']
#
#     def form_valid(self, form):
#         booking = get_object_or_404(Booking, id=self.kwargs['booking_id'])
#
#         # Vérifier que l'utilisateur est le prestataire et que la réservation est terminée
#         if self.request.user != booking.handyman or booking.status != 'completed':
#             return PermissionDenied("Action non autorisée")
#
#         # Créer le paiement
#         payment = form.save(commit=False)
#         payment.booking = booking
#         payment.amount = self.request.POST.get('amount')
#         payment.status = 'completed'  # Pour cet exemple, on suppose que le paiement est complété
#
#         # Montant principal
#         amount = Decimal(self.request.POST.get('amount'))
#         payment.amount = amount
#
#         # Calcul automatique de la commission plateforme, exemple : 10%
#         platform_fee_percent = Decimal('0.10')  # 10%
#         payment.platform_fee = amount * platform_fee_percent
#         payment.save()
#
#         messages.success(self.request, "Paiement enregistré avec succès")
#         return super().form_valid(form)
#
#     def get_success_url(self):
#         booking_id = self.kwargs['booking_id']
#
#         if self.request.user.user_type == 'handyman':
#             return reverse('handy_booking_detail', args=[booking_id])
#         else:
#             return reverse('booking_detail', args=[booking_id])
class AddPaymentView(LoginRequiredMixin, CreateView):
    form_class = PaymentForm
    http_method_names = ['post']

    def form_valid(self, form):
        booking = get_object_or_404(Booking, id=self.kwargs['booking_id'])

        # ✅ L'employeur doit payer
        if self.request.user != booking.client or booking.status != 'completed':
            raise PermissionDenied("Seul l'employeur peut payer une prestation terminée.")

        artisan_profile = booking.handyman.handyman_profile
        amount = Decimal(self.request.POST.get('amount'))
        platform_fee = amount * Decimal('0.11')

        # ✅ Vérifier si la caution est suffisante
        if artisan_profile.deposit_balance < platform_fee:
            messages.error(self.request,
                           "L'artisan n'a pas suffisamment de caution pour couvrir les frais de plateforme.")
            return redirect(self.get_success_url())

        # ✅ Déduire la commission de la caution
        artisan_profile.deposit_balance -= platform_fee
        artisan_profile.save()

        # ✅ Créer le paiement
        payment = form.save(commit=False)
        payment.booking = booking
        payment.amount = amount
        payment.platform_fee = platform_fee
        payment.status = 'completed'
        payment.is_paid = True
        payment.payment_date = timezone.now()
        payment.save()

        messages.success(self.request, "Paiement enregistré et frais de plateforme prélevés sur la caution.")
        return redirect(self.get_success_url())

    def get_success_url(self):
        booking_id = self.kwargs['booking_id']
        return reverse('booking_detail', args=[booking_id])


class ServiceSearchView(ListView):
    model = Service
    template_name = 'services/service_search.html'
    context_object_name = 'services'
    paginate_by = 12

    def get_queryset(self):
        qs = (
            Service.objects.filter(is_active=True, handyman__is_active=True)
            .select_related('handyman', 'category')
            .prefetch_related('images')
        )

        q = self.request.GET.get('q')
        if q:
            qs = qs.filter(
                Q(title__icontains=q) |
                Q(description__icontains=q) |
                Q(category__name__icontains=q) |
                Q(handyman__first_name__icontains=q) |
                Q(handyman__last_name__icontains=q)
            )

        if category := self.request.GET.get('category'):
            qs = qs.filter(category__slug=category)

        if min_price := self.request.GET.get('min_price'):
            qs = qs.filter(price__gte=min_price)

        if max_price := self.request.GET.get('max_price'):
            qs = qs.filter(price__lte=max_price)

        if price_type := self.request.GET.get('price_type'):
            qs = qs.filter(price_type=price_type)

        if rating := self.request.GET.get('rating'):
            qs = qs.annotate(
                avg_rating=Avg('handyman__handyman_bookings__review__rating')
            ).filter(avg_rating__gte=rating)

        if location := self.request.GET.get('location'):
            qs = qs.filter(
                Q(handyman__city__icontains=location) |
                Q(handyman__postal_code__icontains=location)
            )

        sort_by = self.request.GET.get('sort_by', 'newest')
        if sort_by == 'popular':
            qs = qs.annotate(booking_count=Count('bookings')).order_by('-booking_count')
        elif sort_by == 'rating':
            qs = qs.annotate(avg_rating=Avg('handyman__handyman_bookings__review__rating')).order_by(
                F('avg_rating').desc(nulls_last=True))
        elif sort_by == 'price_low':
            qs = qs.order_by('price')
        elif sort_by == 'price_high':
            qs = qs.order_by('-price')
        else:
            qs = qs.order_by('-created_at')

        return qs.distinct()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['request'] = self.request  # Important !

        ctx.update({
            'categories': ServiceCategory.objects.filter(is_active=True).annotate(
                service_count=Count('services', filter=Q(services__is_active=True))
            ),
            'current_query': self.request.GET.get('q', ''),
            'current_category': self.request.GET.get('category'),
            'current_min_price': self.request.GET.get('min_price'),
            'current_max_price': self.request.GET.get('max_price'),
            'current_rating': self.request.GET.get('rating'),
            'current_location': self.request.GET.get('location'),
            'current_price_type': self.request.GET.get('price_type'),
            'current_sort': self.request.GET.get('sort_by', 'newest'),
            'min_price_range': Service.objects.filter(is_active=True).aggregate(min=Min('price'))['min'] or 0,
            'max_price_range': Service.objects.filter(is_active=True).aggregate(max=Max('price'))['max'] or 1000,
            'popular_services': Service.objects.filter(is_active=True)
                                .annotate(booking_count=Count('bookings'))
                                .order_by('-booking_count')[:5]
        })
        return ctx


class ServiceListView(ListView):
    model = Service
    template_name = "employeur/service_list.html"
    paginate_by = 12


class ServiceDetailView(LoginRequiredMixin, DetailView):
    model = Service
    template_name = 'services/service_detail.html'
    context_object_name = 'service'
    slug_field = 'id'
    slug_url_kwarg = 'service_id'

    def get_object(self, queryset=None):
        return get_object_or_404(
            Service.objects.select_related('handyman', 'category')
            .prefetch_related('images', 'bookings'),
            id=self.kwargs['service_id'],
            is_active=True
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = self.object

        # Récupération des avis via les réservations
        reviews = Review.objects.filter(
            booking__service=service
        ).select_related('booking__client')

        # Calcul de la note moyenne et du nombre d'avis
        avg_rating = reviews.aggregate(Avg('rating'))['rating__avg'] or 0
        review_count = reviews.count()

        # Services similaires
        similar_services = Service.objects.filter(
            Q(category=service.category) |
            Q(handyman=service.handyman),
            is_active=True
        ).exclude(id=service.id).select_related('handyman').prefetch_related('images')[:6]

        # Dernières réservations
        recent_bookings = Booking.objects.filter(
            service=service,
            status='completed'
        ).select_related('client')[:5]

        # Disponibilité du prestataire (exemple simplifié)
        today = timezone.now().date()
        next_7_days = [today + timezone.timedelta(days=i) for i in range(1, 8)]

        # Vérifier si l'utilisateur a déjà réservé ce service
        user_has_booked = False
        if self.request.user.is_authenticated:
            user_has_booked = Booking.objects.filter(
                client=self.request.user,
                service=service
            ).exists()

        # Statistiques du prestataire
        handyman = service.handyman
        handyman_stats = {
            'total_services': Service.objects.filter(
                handyman=handyman,
                is_active=True
            ).count(),
            'total_bookings': Booking.objects.filter(
                handyman=handyman,
                status='completed'
            ).count(),
            'response_rate': 95,  # Valeur statique pour l'exemple
            'member_since': handyman.date_joined.strftime("%b %Y")
        }

        context.update({
            'avg_rating': avg_rating,
            'review_count': review_count,
            'reviews': reviews,
            'similar_services': similar_services,
            'recent_bookings': recent_bookings,
            'next_7_days': next_7_days,
            'user_has_booked': user_has_booked,
            'handyman_stats': handyman_stats
        })
        return context


class MyBookingsListView(LoginRequiredMixin, ListView):
    template_name = 'employeur/my_bookings.html'
    context_object_name = 'bookings'
    paginate_by = 10

    def get_queryset(self):
        return Booking.objects.filter(
            client=self.request.user
        ).select_related('service', 'handyman', 'service__category').order_by('-booking_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        status_counts = Booking.objects.filter(
            client=self.request.user
        ).values('status').annotate(count=Count('id'))

        context['status_counts'] = {item['status']: item['count'] for item in status_counts}
        return context


class WorkerProfileView(LoginRequiredMixin, DetailView):
    template_name = 'handyman/worker_profile.html'
    context_object_name = 'worker'

    def get_object(self, queryset=None):
        return get_object_or_404(
            User.objects.select_related('handyman_profile'),
            id=self.kwargs['worker_id'],
            user_type='handyman'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        worker = self.object

        # Services actifs
        services = Service.objects.filter(
            handyman=worker,
            is_active=True
        ).prefetch_related('images', 'category')[:6]

        # Statistiques
        reviews = Review.objects.filter(booking__handyman=worker)
        avg_rating = reviews.aggregate(avg=Avg('rating'))['avg'] or 0
        review_count = reviews.count()

        stats = {
            'total_services': Service.objects.filter(handyman=worker, is_active=True).count(),
            'total_bookings': Booking.objects.filter(handyman=worker, status='completed').count(),
            'response_rate': 95,  # Valeur statique pour l'exemple
            'member_since': worker.date_joined.strftime("%b %Y"),
            'avg_rating': avg_rating,
            'review_count': review_count
        }

        # Disponibilité (exemple)
        today = timezone.now().date()
        next_7_days = [today + timezone.timedelta(days=i) for i in range(1, 8)]

        context.update({
            'services': services,
            'stats': stats,
            'next_7_days': next_7_days
        })
        return context


class CreateBookingView(LoginRequiredMixin, CreateView):
    form_class = BookingForm
    template_name = 'employeur/create_booking.html'

    def get_service(self):
        return get_object_or_404(
            Service.objects.select_related('handyman', 'category'),
            id=self.kwargs['service_id'],
            is_active=True
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['service'] = self.get_service()
        context['today'] = timezone.now().date()
        return context

    def form_valid(self, form):
        service = self.get_service()
        booking = form.save(commit=False)
        booking.client = self.request.user
        booking.handyman = service.handyman
        booking.service = service
        booking.status = 'pending'
        booking.save()
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('my_bookings')


class BookingRespondView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Booking
    form_class = BookingResponseForm
    template_name = 'handyman/booking_respond.html'
    context_object_name = 'booking'

    def test_func(self):
        # Vérifier que l'utilisateur est le prestataire de la réservation
        booking = self.get_object()
        return self.request.user == booking.handyman and booking.status == 'pending'

    def get_object(self):
        return get_object_or_404(
            Booking.objects.select_related('service', 'client', 'handyman'),
            id=self.kwargs['booking_id']
        )

    def form_valid(self, form):
        # Enregistrer la date de réponse
        form.instance.response_date = timezone.now()

        # Enregistrer la réponse
        response = super().form_valid(form)

        # Créer une notification pour le client
        status_display = dict(Booking.STATUS_CHOICES).get(form.instance.status, form.instance.status)
        Notification.objects.create(
            user=form.instance.client,
            notification_type='booking_response',
            message=f"Le prestataire a répondu à votre demande: {status_display}",
            related_id=form.instance.id
        )

        # Message de succès
        messages.success(
            self.request,
            f"Votre réponse a été envoyée avec succès au client"
        )

        return response

    def get_success_url(self):
        return reverse('handydash')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['service'] = self.object.service
        context['client'] = self.object.client
        return context


class BookingActionView(LoginRequiredMixin, View):
    """Vue de base pour les actions sur les réservations"""
    new_status = None
    success_message = None
    notification_message = None
    http_method_names = ['post']  # Accepter uniquement les requêtes POST

    def get_object(self):
        return get_object_or_404(
            Booking.objects.select_related('client', 'handyman'),
            id=self.kwargs['booking_id']
        )

    def test_func(self, booking):
        """Vérifie que l'utilisateur peut effectuer cette action"""
        raise NotImplementedError("La méthode test_func doit être implémentée")

    def perform_action(self, booking):
        """Effectue l'action sur la réservation"""
        booking.status = self.new_status
        booking.save()

        # Créer une notification
        recipient = booking.handyman if self.request.user == booking.client else booking.client
        Notification.objects.create(
            user=recipient,
            notification_type='booking_status',
            message=self.notification_message.format(
                booking_id=booking.id,
                status=booking.get_status_display()
            ),
            related_id=booking.id
        )

        messages.success(self.request, self.success_message)

    def post(self, request, *args, **kwargs):
        booking = self.get_object()

        if not self.test_func(booking):
            return HttpResponseForbidden("Vous n'êtes pas autorisé à effectuer cette action")

        self.perform_action(booking)

        # Redirection basée sur le type d'utilisateur
        if request.user.user_type == 'handyman':
            return redirect(reverse('handyman_booking_detail', args=[booking.id]))
        else:
            return redirect(reverse('booking_detail', args=[booking.id]))


class BookingStartView(BookingActionView):
    new_status = 'in_progress'
    success_message = "Le service a été marqué comme commencé"
    notification_message = "Le statut de la réservation #{booking_id} a changé: {status}"

    def test_func(self, booking):
        # Seul le client ou le prestataire peut démarrer le service
        return self.request.user in [booking.client, booking.handyman] and booking.status == 'confirmed'


class BookingCompleteView(BookingActionView):
    new_status = 'completed'
    success_message = "Le service a été marqué comme terminé"
    notification_message = "Le statut de la réservation #{booking_id} a changé: {status}"

    def test_func(self, booking):
        # Seul le client ou le prestataire peut terminer le service
        return self.request.user in [booking.client, booking.handyman] and booking.status == 'in_progress'

    def perform_action(self, booking):
        super().perform_action(booking)
        booking.end_date = timezone.now()
        booking.save()


class BookingCancelView(BookingActionView):
    new_status = 'cancelled'
    success_message = "La réservation a été annulée"
    notification_message = "La réservation #{booking_id} a été annulée"

    def test_func(self, booking):
        # Seul le client ou le prestataire peut annuler
        user = self.request.user
        return (user == booking.client or user == booking.handyman) and booking.status in ['pending', 'confirmed']


class ServiceCreateView(LoginRequiredMixin, UserPassesTestMixin, CreateView):
    model = Service
    form_class = ServiceForm
    template_name = 'handyman/service_form.html'
    success_url = reverse_lazy('handydash')

    def test_func(self):
        return self.request.user.user_type == "handyman"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['image_formset'] = ServiceImageFormSet(self.request.POST, self.request.FILES)
        else:
            context['image_formset'] = ServiceImageFormSet()
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        image_formset = context['image_formset']

        # Associer le service à l'artisan connecté
        form.instance.handyman = self.request.user

        if image_formset.is_valid():
            self.object = form.save()
            image_formset.instance = self.object
            image_formset.save()
            messages.success(self.request, "Service créé avec succès!")
            return super().form_valid(form)
        else:
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Veuillez corriger les erreurs ci-dessous.")
        return super().form_invalid(form)


class ServiceUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Service
    form_class = ServiceForm
    template_name = 'handyman/service_form.html'
    success_url = reverse_lazy('handydash')

    def test_func(self):
        service = self.get_object()
        return self.request.user == service.handyman

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['image_formset'] = ServiceImageFormSet(
                self.request.POST, self.request.FILES,
                instance=self.object
            )
        else:
            context['image_formset'] = ServiceImageFormSet(instance=self.object)
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        image_formset = context['image_formset']

        if image_formset.is_valid():
            self.object = form.save()
            image_formset.instance = self.object
            image_formset.save()
            messages.success(self.request, "Service mis à jour avec succès!")
            return super().form_valid(form)
        else:
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Veuillez corriger les erreurs ci-dessous.")
        return super().form_invalid(form)


class ServiceStatsView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = Service
    template_name = 'handyman/service_stats.html'
    context_object_name = 'service'

    def test_func(self):
        service = self.get_object()
        return self.request.user == service.handyman

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = self.object

        # Statistiques de base
        context['total_bookings'] = service.bookings.count()
        context['completed_bookings'] = service.bookings.filter(status='completed').count()
        context['cancelled_bookings'] = service.bookings.filter(status='cancelled').count()

        # Calcul du revenu total
        completed_bookings = service.bookings.filter(status='completed')
        total_revenue = sum(
            booking.service.price for booking in completed_bookings
            if booking.service.price and booking.service.price_type != 'quote'
        )
        context['total_revenue'] = total_revenue

        # Évaluation moyenne
        if context['completed_bookings'] > 0:
            total_ratings = sum(booking.rating for booking in completed_bookings if booking.rating)
            context['average_rating'] = total_ratings / context['completed_bookings']
        else:
            context['average_rating'] = 0

        # Dernières réservations (5 dernières)
        context['recent_bookings'] = service.bookings.order_by('-booking_date')[:5]

        return context


class BookingCreateView(LoginRequiredMixin, CreateView):
    model = Booking
    fields = ['service', 'booking_date', 'end_date', 'address', 'city', 'postal_code', 'description']
    template_name = 'employeur/booking_form.html'
    success_url = reverse_lazy('handy:service_list')

    def form_valid(self, form):
        service = form.cleaned_data['service']
        form.instance.client = self.request.user
        form.instance.handyman = service.handyman

        # Calcul automatique du montant
        handyman_profile = service.handyman.handyman_profile
        duration_minutes = 0

        if form.cleaned_data['end_date']:
            duration_minutes = (form.cleaned_data['end_date'] - form.cleaned_data['booking_date']).total_seconds() / 60

        amount = self.calculate_total_amount(service, handyman_profile, duration_minutes)
        form.instance.amount = amount  # ⚡️ Ajoute ce champ dans Booking si tu veux le stocker

        return super().form_valid(form)

    def calculate_total_amount(self, service, handyman_profile, duration_minutes):
        if service.price_type == 'hourly':
            return handyman_profile.hourly_rate * (duration_minutes / 60)
        elif service.price_type == 'daily':
            return handyman_profile.daily_rate
        elif service.price_type == 'monthly':
            return handyman_profile.monthly_rate
        elif service.price_type == 'fixed':
            return service.price
        elif service.price_type == 'quote':
            return 0  # devis négocié
        return 0


class AdminDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):
    template_name = "admin/dashboard.html"

    def test_func(self):
        return self.request.user.is_staff or self.request.user.user_type == "admin"
