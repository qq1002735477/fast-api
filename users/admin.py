from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'is_active', 'created_at')
    list_filter = ('is_active', 'is_staff', 'created_at')
    search_fields = ('username', 'email')
    ordering = ('-created_at',)
