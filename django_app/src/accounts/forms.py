from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm, PasswordResetForm
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from .models import User, UserFavoriteRestaurant
import re


class CustomUserCreationForm(UserCreationForm):
    """
    Enhanced user registration form with email and profile fields.
    """
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address'
        })
    )
    first_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'First name'
        })
    )
    last_name = forms.CharField(
        max_length=30,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Last name'
        })
    )
    city = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'City (optional)'
        })
    )
    state = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'State/Province (optional)'
        })
    )
    country = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Country (optional)'
        })
    )
    birth_month = forms.ChoiceField(
        required=False,
        choices=[('', '-- Select Birth Month --')] + [(i, month) for i, month in [
            (1, 'January'), (2, 'February'), (3, 'March'),
            (4, 'April'), (5, 'May'), (6, 'June'),
            (7, 'July'), (8, 'August'), (9, 'September'),
            (10, 'October'), (11, 'November'), (12, 'December')
        ]],
        widget=forms.Select(attrs={
            'class': 'form-control'
        }),
        help_text='For birthday greetings (optional)'
    )
    newsletter_subscription = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='Subscribe to restaurant recommendations and dining news'
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'city', 'state', 'country', 'birth_month',
                 'password1', 'password2', 'newsletter_subscription')
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Customize password fields
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Create a strong password'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirm your password'
        })
        self.fields['username'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Choose a username'
        })
        
        # Update help texts
        self.fields['password1'].help_text = "Password must be at least 8 characters long and contain letters and numbers."
        self.fields['username'].help_text = "Letters, digits and @/./+/-/_ only."
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError("A user with this email already exists.")
        return email
    
    def clean_password1(self):
        password1 = self.cleaned_data.get('password1')
        
        # Custom password validation
        if len(password1) < 8:
            raise ValidationError("Password must be at least 8 characters long.")
        
        if not re.search(r'[A-Za-z]', password1):
            raise ValidationError("Password must contain at least one letter.")
        
        if not re.search(r'\d', password1):
            raise ValidationError("Password must contain at least one number.")
        
        return password1
    
    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.city = self.cleaned_data.get('city', '')
        user.state = self.cleaned_data.get('state', '')
        user.country = self.cleaned_data.get('country', '')
        user.birth_month = self.cleaned_data.get('birth_month') or None
        user.newsletter_subscription = self.cleaned_data.get('newsletter_subscription', True)
        
        if commit:
            user.save()
        return user


class CustomAuthenticationForm(AuthenticationForm):
    """
    Enhanced login form with email or username support.
    """
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Email or Username',
            'autofocus': True
        }),
        label='Email or Username'
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='Remember me for 30 days'
    )
    
    def clean_username(self):
        username = self.cleaned_data.get('username')
        
        # Allow login with email or username
        if '@' in username:
            try:
                user = User.objects.get(email=username)
                return user.username
            except User.DoesNotExist:
                pass
        
        return username


class CustomPasswordResetForm(PasswordResetForm):
    """
    Enhanced password reset form.
    """
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your email address'
        }),
        help_text="We'll send you a link to reset your password."
    )
    
    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not User.objects.filter(email=email).exists():
            raise ValidationError("No account found with this email address.")
        return email


class UserProfileForm(forms.ModelForm):
    """
    User profile editing form.
    """
    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'email', 'phone_number', 
            'birth_month', 'city', 'state', 'country', 'preferred_cuisines',
            'dietary_restrictions', 'price_range_preference',
            'newsletter_subscription', 'push_notifications'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+1 (555) 123-4567'}),
            'birth_month': forms.Select(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'City'}),
            'state': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'State/Province'}),
            'country': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Country'}),
            'price_range_preference': forms.Select(attrs={'class': 'form-control'}),
            'newsletter_subscription': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'push_notifications': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
    
    preferred_cuisines = forms.MultipleChoiceField(
        required=False,
        choices=[
            ('italian', 'Italian'),
            ('french', 'French'),
            ('japanese', 'Japanese'),
            ('chinese', 'Chinese'),
            ('thai', 'Thai'),
            ('indian', 'Indian'),
            ('mexican', 'Mexican'),
            ('mediterranean', 'Mediterranean'),
            ('american', 'American'),
            ('korean', 'Korean'),
            ('vietnamese', 'Vietnamese'),
            ('spanish', 'Spanish'),
            ('greek', 'Greek'),
            ('middle_eastern', 'Middle Eastern'),
            ('seafood', 'Seafood'),
            ('steakhouse', 'Steakhouse'),
            ('sushi', 'Sushi'),
            ('pizza', 'Pizza'),
        ],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )
    
    dietary_restrictions = forms.MultipleChoiceField(
        required=False,
        choices=[
            ('vegetarian', 'Vegetarian'),
            ('vegan', 'Vegan'),
            ('gluten_free', 'Gluten-Free'),
            ('dairy_free', 'Dairy-Free'),
            ('nut_free', 'Nut-Free'),
            ('halal', 'Halal'),
            ('kosher', 'Kosher'),
            ('low_carb', 'Low Carb'),
            ('keto', 'Keto'),
            ('paleo', 'Paleo'),
            ('pescatarian', 'Pescatarian'),
        ],
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})
    )


class FavoriteRestaurantForm(forms.ModelForm):
    """
    Form for adding/editing favorite restaurants.
    """
    class Meta:
        model = UserFavoriteRestaurant
        fields = ['category', 'personal_rating', 'notes', 'visit_date', 'recommended_dishes']
        widgets = {
            'category': forms.Select(attrs={'class': 'form-control'}),
            'personal_rating': forms.Select(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Share your thoughts about this restaurant...'
            }),
            'visit_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }
    
    recommended_dishes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter dishes separated by commas'
        }),
        help_text="List your favorite dishes from this restaurant"
    )
    
    def clean_recommended_dishes(self):
        dishes = self.cleaned_data.get('recommended_dishes', '')
        if dishes:
            # Convert comma-separated string to list
            return [dish.strip() for dish in dishes.split(',') if dish.strip()]
        return []