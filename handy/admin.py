from .admin_utils import ReadOnlyHistoryAdmin
from handy.admin_safe_delete import SafeDeleteAdminMixin
from .models import (
    HandymanDocument, ServiceImage, Report, PaymentLog, Device, IPBlacklist, ServiceCategory, Service, Booking,
    Notification, Message, DepositTransaction, HeroSlide, Review, UserAddress,
)
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.urls import reverse
from .models import User, HandymanProfile, HandymanDocument
from django.utils.html import format_html

admin.site.site_header = 'Handyman'
admin.site.site_title = 'TRATRA Super Admin Pannel'
admin.site.site_url = 'http://tratra.ci/'
admin.site.index_title = 'TRATRA'
admin.empty_value_display = '**Empty**'

class CustomUserAdmin(SafeDeleteAdminMixin, UserAdmin):
    model = User
    safe_delete_kind = "users"
    # Pas de coordonnées dans la liste : données privées (elles restent dans la fiche, réservée aux superutilisateurs côté Back-Office).
    list_display = ('username', 'first_name', 'last_name', 'phone', 'email', 'is_active', 'is_verified', 'is_staff', 'date_joined', 'last_login')
    list_filter = ('is_active', 'is_verified', 'is_staff', 'is_superuser', 'user_type')
    search_fields = ('username', 'email', 'phone', 'first_name', 'last_name')
    ordering = ('-date_joined',)

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Informations personnelles', {
            'fields': (
                'first_name',
                'last_name',
                'email',
                'phone',
                'profile_picture',
                ('address', 'city', 'postal_code', 'country', 'latitude',
                 'longitude')
            )
        }),
        ('Permissions', {
            'fields': (
                'user_type',
                'is_active',
                'is_staff',
                'is_superuser',
                'is_verified',
                'groups',
                'user_permissions'
            ),
        }),
        ('Dates importantes', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': (
                'username',
                'email',
                'password1',
                'password2',
                'user_type',
                'phone',
                'is_staff',
                'is_superuser',
                'is_verified'
            ),
        }),
    )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        is_superuser = request.user.is_superuser

        if not is_superuser:
            form.base_fields['is_superuser'].disabled = True
            form.base_fields['user_permissions'].disabled = True

        return form


class HandymanDocumentInline(admin.TabularInline):
    model = HandymanDocument
    extra = 1
    readonly_fields = ('uploaded_at', 'preview_document')
    fields = ('document_type', 'file', 'preview_document', 'description', 'uploaded_at')

    def preview_document(self, obj):
        if obj.file:
            return format_html(
                '<a href="{}" target="_blank">Voir le document</a>',
                reverse('handyman-docs-download', kwargs={'pk': obj.pk})
            )
        return "-"

    preview_document.short_description = "Aperçu"


class HandymanProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'rating', 'is_approved', 'profile_completion', 'is_fully_completed')
    list_filter = ('is_approved', 'skills', 'experience_years')
    search_fields = ('user__username', 'user__email', 'user__phone', 'license_number', 'cni_number')
    readonly_fields = (
        'profile_completion', 'rating', 'completed_jobs', 'profile_picture_preview', 'is_fully_completed')
    inlines = [HandymanDocumentInline]
    actions = ['approve_profiles']

    fieldsets = (
        ('Informations utilisateur', {
            'fields': ('user', 'profile_picture_preview')
        }),
        ('Informations professionnelles', {
            'fields': (
                'bio',
                'skills',
                'experience_years',
                ('license_number', 'cni_number'),
                'insurance_info'
            )
        }),
        ('Tarification', {
            'fields': (
                ('hourly_rate', 'daily_rate', 'monthly_rate'),
                'travel_fee'
            )
        }),
        ('Statistiques', {
            'fields': (
                'rating',
                'completed_jobs',
                'profile_completion',
                'is_fully_completed'
            )
        }),
        ('Validation', {
            'fields': ('is_approved', 'availability')
        }),
    )

    def profile_picture_preview(self, obj):
        if obj.photo:
            return format_html(
                '<img src="{}" style="max-height: 200px; max-width: 200px; border-radius: 10px;" />',
                obj.photo.url
            )
        return "Aucune photo"

    profile_picture_preview.short_description = "Photo de profil"

    def profile_completion(self, obj):
        return f"{obj.profile_completion()}%"

    profile_completion.short_description = "Complétion du profil"

    def is_fully_completed(self, obj):
        return obj.is_fully_completed

    is_fully_completed.boolean = True  # Affiche ✅ ou ❌
    is_fully_completed.short_description = "Profil complété"

    @admin.action(description="Approuver les profils sélectionnés")
    def approve_profiles(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, f"{updated} profils ont été approuvés avec succès.")


class HandymanDocumentAdmin(admin.ModelAdmin):
    list_display = ('handyman', 'document_type', 'uploaded_at', 'preview_link')
    list_filter = ('document_type', 'uploaded_at')
    search_fields = ('handyman__user__username', 'handyman__user__email', 'description')
    readonly_fields = ('uploaded_at', 'preview_document')
    date_hierarchy = 'uploaded_at'

    def preview_link(self, obj):
        if obj.file:
            return format_html(
                '<a href="{}" target="_blank">Télécharger</a>',
                reverse('handyman-docs-download', kwargs={'pk': obj.pk})
            )
        return "-"

    preview_link.short_description = "Document"

    def preview_document(self, obj):
        if obj.file:
            return format_html(
                '<a href="{}" target="_blank">Voir le document</a>',
                reverse('handyman-docs-download', kwargs={'pk': obj.pk})
            )
        return "-"

    preview_document.short_description = "Aperçu"


# Désenregistrer le modèle User par défaut s'il est déjà enregistré
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

# Enregistrer les modèles avec les classes d'admin personnalisées
admin.site.register(User, CustomUserAdmin)
admin.site.register(HandymanProfile, HandymanProfileAdmin)
admin.site.register(HandymanDocument, HandymanDocumentAdmin)


@admin.register(ServiceImage)
class ServiceImageAdmin(admin.ModelAdmin):
    list_display = ('service', 'uploaded_at')


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ('reporter', 'report_type', 'is_resolved', 'created_at')
    list_filter = ('report_type', 'is_resolved')


@admin.register(PaymentLog)
class PaymentLogAdmin(admin.ModelAdmin):
    list_display = ('payment', 'previous_status', 'new_status', 'changed_at')


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_type', 'last_active')


@admin.register(IPBlacklist)
class IPBlacklistAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'is_active', 'reason', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('ip_address', 'reason')


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'parent', 'is_active', 'display_icon')
    list_filter = ('is_active', 'parent')
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('display_icon',)

    def display_icon(self, obj):
        return format_html(f'<i class="fa fa-{obj.icon}"></i> {obj.icon}') if obj.icon else '-'

    display_icon.short_description = 'Icon Preview'


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('title', 'handyman', 'category', 'price_type', 'price', 'is_active')
    list_filter = ('is_active', 'requires_travel', 'price_type', 'category')
    search_fields = ('title', 'description', 'handyman__username', 'handyman__email')
    raw_id_fields = ('handyman', 'category')  # Pour les relations avec beaucoup d'instances
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        (None, {'fields': ('handyman', 'category', 'title', 'description','banner','image_url')}),
        ('Pricing', {'fields': ('price_type', 'price', 'duration', 'requires_travel')}),
        ('Status', {'fields': ('is_active',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at')}),
    )


# @admin.register(ServiceImage)
# class ServiceImageAdmin(admin.ModelAdmin):
#     list_display = ('service', 'image_preview', 'alt_text', 'uploaded_at')
#     search_fields = ('service__title', 'alt_text')
#     readonly_fields = ('uploaded_at', 'image_preview')
#
#     def image_preview(self, obj):
#         return format_html('<img src="{}" height="50" />'.format(obj.image.url)) if obj.image else '-'
#
#     image_preview.short_description = 'Preview'


@admin.register(Booking)
class BookingAdmin(SafeDeleteAdminMixin, admin.ModelAdmin):
    safe_delete_kind = "bookings"
    list_display = ('id', 'client', 'handyman', 'service', 'booking_date', 'status', 'transport_fee', 'short_address')
    list_filter = ('status', 'city', 'booking_date')
    search_fields = ('client__username', 'handyman__username', 'address', 'city', 'postal_code')
    raw_id_fields = ('client', 'handyman', 'service')
    # Le déplacement est calculé par le serveur et FIGÉ à la réservation (tarif, distance, créneau, version) : jamais modifié à la main.
    readonly_fields = ('created_at', 'updated_at', 'transport_fee', 'transport_quote')
    date_hierarchy = 'booking_date'

    def short_address(self, obj):
        return f"{obj.address[:30]}..." if len(obj.address) > 30 else obj.address

    short_address.short_description = 'Address'

    search_fields = ('id', 'booking__id')
    # filter_horizontal = ('participants',)
    list_filter = ('created_at',)
    date_hierarchy = 'created_at'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'is_read', 'created_at')
    search_fields = ('conversation__id', 'sender__email', 'content')
    list_filter = ('is_read', 'created_at')
    date_hierarchy = 'created_at'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('user__email', 'message')
    date_hierarchy = 'created_at'


@admin.register(DepositTransaction)
class DepositTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'handyman', 'type', 'amount', 'status', 'reference', 'date')
    list_filter = ('status', 'type')
    search_fields = ('handyman__email', 'reference')

@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    list_display = ('title', 'cta_action', 'is_active', 'ordering', 'starts_at', 'ends_at')
    list_filter = ('is_active', 'cta_action')
    search_fields = ('title', 'subtitle')
    ordering = ('ordering', '-id')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ("Contenu", {
            'fields': ('title', 'subtitle', 'image', 'image_url')
        }),
        ("Style", {
            'fields': ('gradient_start', 'gradient_end')
        }),
        ("CTA", {
            'fields': ('cta_label', 'cta_action', 'category', 'target_url')
        }),
        ("Activation", {
            'fields': ('is_active', 'ordering', 'starts_at', 'ends_at')
        }),
        ("Meta", {
            'fields': ('created_by', 'created_at', 'updated_at')
        }),
    )


@admin.register(UserAddress)
class UserAddressAdmin(ReadOnlyHistoryAdmin, admin.ModelAdmin):
    """Adresses des comptes : lecture seule, SANS coordonnées (données privées) ; elles se corrigent depuis l'application du titulaire."""
    list_display = ('user', 'label', 'city', 'commune', 'is_primary', 'is_favorite', 'coords_source', 'updated_at')
    list_filter = ('is_primary', 'is_favorite', 'coords_source', 'country')
    search_fields = ('user__username', 'user__phone', 'user__first_name', 'user__last_name', 'city', 'commune', 'street')
    raw_id_fields = ('user',)
    exclude = ('latitude', 'longitude')


@admin.register(Review)
class ReviewAdmin(ReadOnlyHistoryAdmin, admin.ModelAdmin):
    """Avis clients : lecture seule (la modération — masquer, republier — se fait dans le Back-Office, motivée et journalisée)."""
    list_display = ('id', 'booking', 'rating', 'is_hidden', 'revealed_at', 'created_at')
    list_filter = ('is_hidden', 'rating', ('revealed_at', admin.EmptyFieldListFilter))
    search_fields = ('booking__id', 'booking__client__username', 'booking__handyman__username', 'comment')
    raw_id_fields = ('booking',)
    date_hierarchy = 'created_at'
