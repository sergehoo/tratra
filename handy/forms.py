from allauth.account.forms import SignupForm
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from handy.models import User, HandymanProfile, Service, ServiceImage, ServiceCategory, Booking, Payment, Review, \
    Message

# Jours standards
DAYS = [
    ('monday', 'Lundi'),
    ('tuesday', 'Mardi'),
    ('wednesday', 'Mercredi'),
    ('thursday', 'Jeudi'),
    ('friday', 'Vendredi'),
    ('saturday', 'Samedi'),
    ('sunday', 'Dimanche'),
]

# Créneaux standards
SLOTS = [
    ('morning', 'Matin (8h-12h)'),
    ('afternoon', 'Après-midi (12h-17h)'),
    ('evening', 'Soirée (17h-21h)'),
]

# Compose les combinaisons : ('monday_morning', 'Lundi - Matin')
AVAILABILITY_CHOICES = [
    (f"{day[0]}_{slot[0]}", f"{day[1]} - {slot[1]}")
    for day in DAYS for slot in SLOTS
]


class CustomSignupForm(SignupForm):
    USER_TYPES = (
        ('employeur', 'Employeur'),
        ('handyman', 'Artisan'),
    )

    first_name = forms.CharField(max_length=30, label="Prénom")
    last_name = forms.CharField(max_length=30, label="Nom")
    phone = forms.CharField(max_length=20, label="Téléphone")
    address = forms.CharField(widget=forms.Textarea, label="Adresse", required=False)
    city = forms.CharField(max_length=100, label="Ville", required=False)
    postal_code = forms.CharField(max_length=20, label="Code Postal", required=False)
    country = forms.CharField(max_length=100, label="Pays", required=False)
    profile_picture = forms.ImageField(label="Photo de profil", required=False)
    user_type = forms.ChoiceField(choices=USER_TYPES, label="Type d'utilisateur", required=False)
    latitude = forms.DecimalField(required=False, widget=forms.HiddenInput)
    longitude = forms.DecimalField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        # Préremplir user_type si présent en GET
        if self.request:
            user_type = self.request.GET.get('user_type')
            if user_type in dict(self.USER_TYPES).keys():
                self.initial['user_type'] = user_type
            if self.initial.get('user_type'):
                self.fields['user_type'].disabled = True

    def save(self, request):
        user = super().save(request)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.phone = self.cleaned_data['phone']
        user.address = self.cleaned_data['address']
        user.city = self.cleaned_data['city']
        user.postal_code = self.cleaned_data['postal_code']
        user.country = self.cleaned_data['country']
        user.user_type = self.cleaned_data['user_type']
        user.latitude = self.cleaned_data.get('latitude')
        user.longitude = self.cleaned_data.get('longitude')

        # Gérer la photo si fournie
        if self.cleaned_data.get('profile_picture'):
            user.profile_picture = self.cleaned_data['profile_picture']

        user.save()
        return user


class EmployerSignupForm(SignupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('user_type', None)  # plus utile car fixé

    first_name = forms.CharField(max_length=30, label="Prénom")
    last_name = forms.CharField(max_length=30, label="Nom")
    phone = forms.CharField(max_length=20, label="Téléphone")

    # Champs employeur seulement
    company_name = forms.CharField(max_length=100, label="Nom de l'entreprise", required=False)

    def save(self, request):
        user = super().save(request)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.phone = self.cleaned_data['phone']
        user.user_type = 'employeur'
        user.save()
        return user


class HandymanSignupForm(SignupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('user_type', None)  # plus utile car fixé

    first_name = forms.CharField(max_length=30, label="Prénom")
    last_name = forms.CharField(max_length=30, label="Nom")
    phone = forms.CharField(max_length=20, label="Téléphone")

    # Champs artisan seulement
    license_number = forms.CharField(max_length=100, label="Numéro de licence", required=False)
    profile_picture = forms.ImageField(label="Photo de profil", required=False)

    def save(self, request):
        user = super().save(request)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.phone = self.cleaned_data['phone']
        user.user_type = 'handyman'
        if self.cleaned_data.get('profile_picture'):
            user.profile_picture = self.cleaned_data['profile_picture']
        user.save()
        return user


# class HandymanProfileForm(forms.ModelForm):
#     availability_choices = forms.MultipleChoiceField(
#         choices=AVAILABILITY_CHOICES,
#         required=False,
#         widget=forms.SelectMultiple(attrs={
#             'class': 'w-full select2-multiple',
#             'data-placeholder': 'Sélectionnez vos créneaux disponibles...'
#         }),
#         label="Disponibilités"
#     )
#     class Meta:
#         model = HandymanProfile
#         fields = [
#             'bio',
#             'skills',
#             'experience_years',
#             'license_number',
#             'cni_number',
#             'insurance_info',
#             'hourly_rate',
#             'daily_rate',
#             'monthly_rate',
#             'travel_fee',
#             'photo',
#         ]
#         widgets = {
#             'bio': forms.Textarea(attrs={
#                 'rows': 3,
#                 'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'placeholder': 'Décrivez vos compétences, votre expérience et votre approche du travail...'
#             }),
#             'skills': forms.SelectMultiple(attrs={
#                 'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition'
#             }),
#             'experience_years': forms.NumberInput(attrs={
#                 'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'min': 0,
#                 'max': 50
#             }),
#             'license_number': forms.TextInput(attrs={
#                 'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'placeholder': 'Numéro de licence professionnelle'
#             }),
#             'cni_number': forms.TextInput(attrs={
#                 'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'placeholder': 'Numéro de carte nationale d\'identité'
#             }),
#             'insurance_info': forms.Textarea(attrs={
#                 'rows': 2,
#                 'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'placeholder': 'Nom de l\'assureur, numéro de police, date d\'expiration...'
#             }),
#             'hourly_rate': forms.NumberInput(attrs={
#                 'class': 'w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'min': 0,
#                 'step': 500
#             }),
#             'daily_rate': forms.NumberInput(attrs={
#                 'class': 'w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'min': 0,
#                 'step': 1000
#             }),
#             'monthly_rate': forms.NumberInput(attrs={
#                 'class': 'w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'min': 0,
#                 'step': 5000
#             }),
#             'travel_fee': forms.NumberInput(attrs={
#                 'class': 'w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'min': 0,
#                 'step': 500
#             }),
#             'availability': forms.Textarea(attrs={
#                 'rows': 3,
#                 'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
#                 'placeholder': 'Ex: Lundi-Vendredi: 8h-18h, Samedi: 9h-13h, Dimanche: fermé'
#             }),
#             'photo': forms.ClearableFileInput(attrs={
#                 'class': 'w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-green-50 file:text-green-700 hover:file:bg-green-100'
#             }),
#         }
#
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         # Remplit Select2 avec valeurs déjà enregistrées
#         if self.instance and self.instance.availability:
#             selected = []
#             for day, slots in self.instance.availability.items():
#                 for slot in slots:
#                     selected.append(f"{day}_{slot}")
#             self.fields['availability_choices'].initial = selected
#
#         # Ajout de préfixes monétaires pour les champs de tarification
#         self.fields['hourly_rate'].widget.attrs[
#             'class'] += ' bg-no-repeat bg-left pl-10 bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' class=\'h-5 w-5\' viewBox=\'0 0 20 20\' fill=\'%234B5563\'%3E%3Cpath fill-rule=\'evenodd\' d=\'M10 18a8 8 0 100-16 8 8 0 000 16zM8.736 6.979C9.208 6.193 9.696 6 10 6c.304 0 .792.193 1.264.979a1 1 0 001.715-1.029C12.279 4.784 11.232 4 10 4s-2.279.784-2.979 1.95a1 1 0 101.715 1.029zM6 11.5a1 1 0 100-2 1 1 0 000 2zm7-1a1 1 0 11-2 0 1 1 0 012 0z\' clip-rule=\'evenodd\' /%3E%3C/svg%3E")]'
#         self.fields['daily_rate'].widget.attrs[
#             'class'] += ' bg-no-repeat bg-left pl-10 bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' class=\'h-5 w-5\' viewBox=\'0 0 20 20\' fill=\'%234B5563\'%3E%3Cpath fill-rule=\'evenodd\' d=\'M10 18a8 8 0 100-16 8 8 0 000 16zM8.736 6.979C9.208 6.193 9.696 6 10 6c.304 0 .792.193 1.264.979a1 1 0 001.715-1.029C12.279 4.784 11.232 4 10 4s-2.279.784-2.979 1.95a1 1 0 101.715 1.029zM6 11.5a1 1 0 100-2 1 1 0 000 2zm7-1a1 1 0 11-2 0 1 1 0 012 0z\' clip-rule=\'evenodd\' /%3E%3C/svg%3E")]'
#         self.fields['monthly_rate'].widget.attrs[
#             'class'] += ' bg-no-repeat bg-left pl-10 bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' class=\'h-5 w-5\' viewBox=\'0 0 20 20\' fill=\'%234B5563\'%3E%3Cpath fill-rule=\'evenodd\' d=\'M10 18a8 8 0 100-16 8 8 0 000 16zM8.736 6.979C9.208 6.193 9.696 6 10 6c.304 0 .792.193 1.264.979a1 1 0 001.715-1.029C12.279 4.784 11.232 4 10 4s-2.279.784-2.979 1.95a1 1 0 101.715 1.029zM6 11.5a1 1 0 100-2 1 1 0 000 2zm7-1a1 1 0 11-2 0 1 1 0 012 0z\' clip-rule=\'evenodd\' /%3E%3C/svg%3E")]'
#         self.fields['travel_fee'].widget.attrs[
#             'class'] += ' bg-no-repeat bg-left pl-10 bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' class=\'h-5 w-5\' viewBox=\'0 0 20 20\' fill=\'%234B5563\'%3E%3Cpath fill-rule=\'evenodd\' d=\'M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z\' clip-rule=\'evenodd\' /%3E%3C/svg%3E")]'
#
#         # Ajout de placeholders manquants
#         self.fields['skills'].widget.attrs['placeholder'] = 'Sélectionnez vos compétences'
#         self.fields['insurance_info'].widget.attrs['placeholder'] = 'Détails de votre assurance professionnelle'
#
#         # Personnalisation du champ de photo
#         self.fields['photo'].widget.attrs['accept'] = 'image/*'
#
#     def save(self, commit=True):
#         instance = super().save(commit=False)
#
#         # Rebuild availability JSON depuis MultiChoice
#         availability_data = {}
#         for item in self.cleaned_data['availability_choices']:
#             day, slot = item.split('_')
#             availability_data.setdefault(day, []).append(slot)
#
#         instance.availability = availability_data
#
#         if commit:
#             instance.save()
#             self.save_m2m()
#         return instance

# forms.py
DAY_CHOICES = [
    ('Lundi', 'Lundi'),
    ('Mardi', 'Mardi'),
    ('Mercredi', 'Mercredi'),
    ('Jeudi', 'Jeudi'),
    ('Vendredi', 'Vendredi'),
    ('Samedi', 'Samedi'),
    ('Dimanche', 'Dimanche'),
]
SLOT_CHOICES = [
    ('matin', 'Matin (8h-12h)'),
    ('aprem', 'Après-midi (14h-18h)'),
    ('soir', 'Soir (18h-22h)'),
    ('nuit', 'Nuit (22h-6h)'),
]


class HandymanProfileForm(forms.ModelForm):
    # Définition structurée des choix de disponibilités

    # Création des choix combinés
    AVAILABILITY_CHOICES = [
        (f"{day}_{slot}", f"{day} - {text}")
        for day, _ in DAY_CHOICES
        for slot, text in SLOT_CHOICES
    ]

    availability_choices = forms.MultipleChoiceField(
        choices=AVAILABILITY_CHOICES,
        required=False,
        widget=forms.SelectMultiple(attrs={
            'class': 'w-full select2-multiple',
            'data-placeholder': 'Sélectionnez vos créneaux disponibles...'
        }),
        label="Disponibilités"
    )

    class Meta:
        model = HandymanProfile
        fields = [
            'bio',
            'skills',
            'experience_years',
            'license_number',
            'cni_number',
            'insurance_info',
            'hourly_rate',
            'daily_rate',
            'monthly_rate',
            'travel_fee',
            'photo',
        ]
        widgets = {
            'bio': forms.Textarea(attrs={
                'rows': 3,
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'placeholder': 'Décrivez vos compétences, expérience et approche...'
            }),
            'skills': forms.SelectMultiple(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition select2-multiple'
            }),
            'experience_years': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'min': 0,
                'max': 50
            }),
            'license_number': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'placeholder': 'Numéro de licence professionnelle'
            }),
            'cni_number': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'placeholder': 'Numéro CNI'
            }),
            'insurance_info': forms.Textarea(attrs={
                'rows': 2,
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'placeholder': 'Assureur, numéro police, expiration...'
            }),
            'hourly_rate': forms.NumberInput(attrs={
                'class': 'w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'min': 0,
                'step': 500
            }),
            'daily_rate': forms.NumberInput(attrs={
                'class': 'w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'min': 0,
                'step': 1000
            }),
            'monthly_rate': forms.NumberInput(attrs={
                'class': 'w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'min': 0,
                'step': 5000
            }),
            'travel_fee': forms.NumberInput(attrs={
                'class': 'w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'min': 0,
                'step': 500
            }),
            'photo': forms.ClearableFileInput(attrs={
                'class': 'w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-green-50 file:text-green-700 hover:file:bg-green-100',
                'accept': 'image/*',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialisation des disponibilités
        if self.instance and self.instance.availability:
            selected = []
            for day, slots in self.instance.availability.items():
                for slot in slots:
                    selected.append(f"{day}_{slot}")
            self.fields['availability_choices'].initial = selected

        # Configuration des icônes monétaires
        currency_icon = 'bg-no-repeat bg-left pl-10 bg-[url("data:image/svg+xml,%3Csvg...")]'
        for field in ['hourly_rate', 'daily_rate', 'monthly_rate']:
            self.fields[field].widget.attrs['class'] += f' {currency_icon}'

        # Configuration spécifique pour les frais de déplacement
        self.fields['travel_fee'].widget.attrs[
            'class'] += ' bg-no-repeat bg-left pl-10 bg-[url("data:image/svg+xml,%3Csvg...")]'

        # Placeholders manquants
        self.fields['skills'].widget.attrs['placeholder'] = 'Sélectionnez vos compétences'
        self.fields['insurance_info'].widget.attrs['placeholder'] = 'Détails assurance professionnelle'
        self.fields['photo'].widget.attrs['accept'] = 'image/*'

    def clean(self):
        cleaned_data = super().clean()

        # Validation cohérente des tarifs
        price_fields = {
            'hourly_rate': cleaned_data.get('hourly_rate'),
            'daily_rate': cleaned_data.get('daily_rate'),
            'monthly_rate': cleaned_data.get('monthly_rate'),
        }

        for field, value in price_fields.items():
            if value is not None and value < 0:
                self.add_error(field, "Le tarif ne peut pas être négatif")

        # Validation CNI
        cni_number = cleaned_data.get('cni_number')
        if cni_number and not cni_number.isalnum():
            self.add_error('cni_number', "Numéro CNI invalide")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        # Construction des disponibilités
        availability_data = {}
        for item in self.cleaned_data.get('availability_choices', []):
            day, slot = item.split('_', 1)
            availability_data.setdefault(day, []).append(slot)

        instance.availability = availability_data

        if commit:
            instance.save()
            self.save_m2m()

        return instance


class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = [
            'category', 'title', 'description',
            'price_type', 'price', 'duration', 'is_active'
        ]
        widgets = {
            'description': forms.Textarea(attrs={
                'rows': 4,
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition'
            }),
            'price': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'step': '500'
            }),
            'duration': forms.NumberInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'min': '15',
                'step': '15'
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        # Filtrer les catégories actives
        self.fields['category'].queryset = ServiceCategory.objects.filter(is_active=True)

        # Personnalisation des champs
        self.fields['price_type'].widget.attrs.update({
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition'
        })
        self.fields['category'].widget.attrs.update({
            'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition'
        })
        self.fields['is_active'].widget.attrs.update({
            'class': 'w-5 h-5 text-green-600 border-gray-300 rounded focus:ring-green-500'
        })

    def clean_price(self):
        price_type = self.cleaned_data.get('price_type')
        price = self.cleaned_data.get('price')

        if price_type in ['hourly', 'fixed'] and price is None:
            raise forms.ValidationError("Un prix est requis pour ce type de tarification.")

        if price_type == 'quote' and price is not None:
            raise forms.ValidationError("Le prix doit être vide pour les services sur devis.")

        return price

    def clean_duration(self):
        duration = self.cleaned_data.get('duration')
        price_type = self.cleaned_data.get('price_type')

        if price_type == 'hourly' and duration is None:
            raise forms.ValidationError("La durée est requise pour les services horaires.")

        return duration


class ServiceImageForm(forms.ModelForm):
    class Meta:
        model = ServiceImage
        fields = ['image', 'alt_text']
        widgets = {
            'image': forms.ClearableFileInput(attrs={
                'class': 'w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-semibold file:bg-green-50 file:text-green-700 hover:file:bg-green-100'
            }),
            'alt_text': forms.TextInput(attrs={
                'class': 'w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-green-500 transition',
                'placeholder': 'Description de l\'image'
            }),
        }


ServiceImageFormSet = forms.inlineformset_factory(
    Service,
    ServiceImage,
    form=ServiceImageForm,
    extra=3,
    max_num=5,
    can_delete=True
)


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ['booking_date', 'address', 'city', 'postal_code', 'description']
        widgets = {
            'booking_date': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.now()
        min_date = now + timezone.timedelta(hours=24)  # Minimum 24h à l'avance
        self.fields['booking_date'].widget.attrs['min'] = min_date.strftime('%Y-%m-%dT%H:%M')

    def clean_booking_date(self):
        booking_date = self.cleaned_data['booking_date']
        now = timezone.now()

        if booking_date < now + timezone.timedelta(hours=24):
            raise forms.ValidationError("La réservation doit être faite au moins 24 heures à l'avance.")

        return booking_date


class BookingResponseForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ['status', 'proposed_price', 'handyman_comment']
        widgets = {
            'handyman_comment': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': "Ajoutez un commentaire ou des détails supplémentaires..."
            }),
            'status': forms.RadioSelect(choices=(
                ('confirmed', 'Accepter la demande'),
                ('declined', 'Refuser la demande'),
            ))
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ajuster les champs en fonction du type de prix du service
        if self.instance.service and self.instance.service.price_type != 'quote':
            self.fields['proposed_price'].disabled = True
            self.fields['proposed_price'].help_text = "Le prix est fixé par le service"
        else:
            self.fields['proposed_price'].required = True

    def clean(self):
        cleaned_data = super().clean()
        status = cleaned_data.get('status')
        proposed_price = cleaned_data.get('proposed_price')

        # Validation pour les services sur devis
        if status == 'confirmed' and self.instance.service.price_type == 'quote':
            if not proposed_price or proposed_price <= 0:
                self.add_error('proposed_price', "Veuillez entrer un prix valide pour ce devis")

        return cleaned_data


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ['content']
        widgets = {
            'content': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Écrivez votre message...',
                'class': 'w-full px-4 py-2 border rounded-lg focus:ring-employer focus:border-employer'
            })
        }


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['rating', 'comment']
        widgets = {
            'rating': forms.RadioSelect(choices=[(i, i) for i in range(1, 6)]),
            'comment': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Décrivez votre expérience...',
                'class': 'w-full px-4 py-2 border rounded-lg focus:ring-employer focus:border-employer'
            })
        }


class PaymentForm(forms.ModelForm):
    class Meta:
        model = Payment
        fields = ['method', 'transaction_id']
        widgets = {
            'method': forms.Select(attrs={
                'class': 'w-full px-4 py-2 border rounded-lg focus:ring-employer focus:border-employer'
            }),
            'transaction_id': forms.TextInput(attrs={
                'placeholder': 'ID de transaction',
                'class': 'w-full px-4 py-2 border rounded-lg focus:ring-employer focus:border-employer'
            })
        }


class DepositTopUpForm(forms.Form):
    amount = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=1000,
        label="Montant de la caution",
        widget=forms.NumberInput(attrs={
            'class': 'w-full px-4 py-2 border rounded-lg',
            'placeholder': 'Montant FCFA'
        })
    )
