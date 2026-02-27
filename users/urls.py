"""
User authentication URL configuration.
"""
from django.urls import path
from .views import (
    UserRegistrationView,
    UserLoginView,
    CustomTokenRefreshView,
    UserProfileView,
)

urlpatterns = [
    path('register/', UserRegistrationView.as_view(), name='register'),
    path('login/', UserLoginView.as_view(), name='login'),
    path('token/refresh/', CustomTokenRefreshView.as_view(), name='token_refresh'),
    path('profile/', UserProfileView.as_view(), name='profile'),
]
