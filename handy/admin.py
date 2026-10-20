from .admin_utils import ReadOnlyHistoryAdmin
from handy.admin_safe_delete import SafeDeleteAdminMixin
from .models import (
    HandymanDocument, ServiceImage, Report, PaymentLog, Device, IPBlacklist, ServiceCategory, Service, Booking,
    Notification, Message, DepositTransaction, HeroSlide, Review, UserAddress,
)
from django import forms
from django.contrib import admin
from django.db.models import Count, Q
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
                ('experience_years', 'experience_label'),
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


class CategoryKindFilter(admin.SimpleListFilter):
    title = "Niveau"
    parameter_name = "kind"

    def lookups(self, request, model_admin):
        return [("trade", "Métiers (catégories racines)"), ("service", "Prestations (sous-catégories)")]

    def queryset(self, request, queryset):
        if self.value() == "trade":
            return queryset.filter(parent__isnull=True)
        if self.value() == "service":
            return queryset.filter(parent__isnull=False)
        return queryset


class TradeFilter(admin.SimpleListFilter):
    """Un métier et toutes ses prestations (la liste n'affiche que les métiers, pas toutes les catégories comme le filtre « parent » par défaut)."""
    title = "Métier"
    parameter_name = "trade"

    def lookups(self, request, model_admin):
        return [(c.pk, c.name) for c in ServiceCategory.objects.filter(parent__isnull=True).order_by("position", "name")]

    def queryset(self, request, queryset):
        if self.value() and self.value().isdigit():
            return queryset.filter(Q(pk=self.value()) | Q(parent_id=self.value()) | Q(parent__parent_id=self.value()))
        return queryset


class ServiceCategoryAdminForm(forms.ModelForm):
    class Meta:
        model = ServiceCategory
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "min_experience_years" in self.fields:
            self.fields["min_experience_years"].required = False      # vide = 0 : débutants acceptés

    def clean_min_experience_years(self):
        return self.cleaned_data.get("min_experience_years") or 0

    def clean_icon(self):
        icon = (self.cleaned_data.get("icon") or "").strip()
        if icon and "icon" in self.changed_data:
            from handy import catalog

            key = catalog.icon_key(icon, "")
            if not catalog.icon_known(key):
                raise forms.ValidationError(f"Icône « {key or icon} » non reconnue : le site et l'application afficheraient l'icône par défaut. "
                                            "Utilisez un nom Font Awesome de la liste (ex. « fa-solid fa-utensils », « fa-solid fa-baby »).")
        return icon or None

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")
        if parent and self.instance.pk:
            node = parent
            while node is not None:                # une catégorie ne peut pas devenir sa propre prestation (cycle)
                if node.pk == self.instance.pk:
                    raise forms.ValidationError("Une catégorie ne peut pas être placée sous elle-même ni sous l'une de ses prestations.")
                node = node.parent
        return parent


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    """Catalogue unique : MÉTIER (catégorie racine), PRESTATION (sous-catégorie), OFFRE (service publié par un professionnel).
    Visibilité, ordre et mise en avant se règlent ici et se retrouvent à l'identique sur le site et dans l'application (`GET /handy/catalog/`)."""
    form = ServiceCategoryAdminForm
    list_display = ('name', 'level', 'trade_name', 'slug', 'position', 'is_featured', 'is_active', 'offers', 'display_icon')
    list_editable = ('position', 'is_featured', 'is_active')
    list_filter = (CategoryKindFilter, TradeFilter, 'is_active', 'is_featured')
    search_fields = ('name', 'slug', 'description')
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ('display_icon',)
    ordering = ('position', 'name')
    list_per_page = 100
    actions = ('feature', 'unfeature', 'show', 'hide')
    fieldsets = (
        ('Identité', {'fields': ('name', 'slug', 'parent', 'description'),
                      'description': "Sans parent : c'est un MÉTIER. Avec un parent : c'est une PRESTATION de ce métier. Les offres des professionnels se rattachent à une catégorie."}),
        ('Affichage', {'fields': ('is_active', 'is_featured', 'position'),
                       'description': "Actif = visible sur le site et dans l'application (même sans offre). Mise en avant = page d'accueil. Ordre : le plus petit d'abord."}),
        ('Publication', {'fields': ('min_experience_years',),
                         'description': "Expérience minimale exigée pour publier une offre de ce métier (0 = débutants acceptés). "
                                        "Un artisan qui déclare moins n'est pas publié ; sa déclaration n'est jamais modifiée."}),
        ('Icône', {'fields': ('icon', 'display_icon'), 'description': "Nom Font Awesome, par exemple « fa-solid fa-utensils ». Le même nom donne la même icône sur le site et dans l'application."}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('parent').annotate(
            offers_n=Count('services', filter=Q(services__is_active=True), distinct=True))

    @admin.display(description='Niveau', ordering='parent')
    def level(self, obj):
        return 'Métier' if obj.parent_id is None else 'Prestation'

    @admin.display(description='Métier')
    def trade_name(self, obj):
        node = obj
        while node.parent_id is not None:
            node = node.parent
        return node.name if node.pk != obj.pk else '—'

    @admin.display(description='Offres actives', ordering='offers_n')
    def offers(self, obj):
        return obj.offers_n

    @admin.display(description='Icône')
    def display_icon(self, obj):
        from handy import catalog

        key = catalog.icon_key(obj.icon, obj.slug)
        if not key:
            return format_html('<span style="color:#b45309">Aucune icône : icône par défaut</span>')
        if not catalog.icon_known(key):
            return format_html('<code>{}</code> <span style="color:#b91c1c">non reconnue : icône par défaut affichée</span>', key)
        return format_html('<code>{}</code> ✓', key)

    def _bulk(self, request, queryset, message, **changes):
        n = queryset.update(**changes)
        from handy import catalog

        catalog.invalidate()
        self.message_user(request, message.format(n=n))

    @admin.action(description="Mettre en avant sur la page d'accueil")
    def feature(self, request, queryset):
        self._bulk(request, queryset, "{n} catégorie(s) mise(s) en avant.", is_featured=True)

    @admin.action(description="Retirer de la mise en avant")
    def unfeature(self, request, queryset):
        self._bulk(request, queryset, "{n} catégorie(s) retirée(s) de la mise en avant.", is_featured=False)

    @admin.action(description="Rendre visible (actif)")
    def show(self, request, queryset):
        self._bulk(request, queryset, "{n} catégorie(s) rendue(s) visible(s).", is_active=True)

    @admin.action(description="Masquer (inactif) — les prestations d'un métier masqué le sont aussi")
    def hide(self, request, queryset):
        self._bulk(request, queryset, "{n} catégorie(s) masquée(s).", is_active=False)


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


# ---- Inscription accompagnée : questions configurables par métier ----
from .models import OnboardingQuestion, ProOnboarding  # noqa: E402


@admin.register(OnboardingQuestion)
class OnboardingQuestionAdmin(admin.ModelAdmin):
    """Questions posées une par une (réponses en gros boutons). `options` : liste JSON de
    {"value", "label", "emoji", "phrase" (texte de l'annonce), "years" (expérience), "amount" + "unit" (hour|day|month|job|quote)}."""
    list_display = ("text", "key", "target", "kind", "trade_keywords", "position", "required", "is_active")
    list_editable = ("position", "is_active")
    list_filter = ("target", "kind", "is_active")
    search_fields = ("text", "key", "trade_keywords")
    filter_horizontal = ("trades",)


@admin.register(ProOnboarding)
class ProOnboardingAdmin(admin.ModelAdmin):
    """Suivi des inscriptions accompagnées (lecture seule : les réponses appartiennent à l'utilisateur)."""
    list_display = ("user", "path", "trade", "commune", "step", "applied_at", "updated_at")
    list_filter = ("path", "applied_at")
    search_fields = ("user__username", "user__phone", "commune")
    readonly_fields = [f.name for f in ProOnboarding._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
