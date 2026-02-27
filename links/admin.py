from django.contrib import admin
from .models import Link, AccessLog, Group, Tag


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ('short_code', 'original_url', 'user', 'click_count', 'created_at', 'is_active')
    list_filter = ('is_active', 'created_at', 'group')
    search_fields = ('short_code', 'original_url', 'user__username')
    ordering = ('-created_at',)
    readonly_fields = ('click_count', 'created_at', 'updated_at')


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ('link', 'ip_address', 'accessed_at')
    list_filter = ('accessed_at',)
    search_fields = ('link__short_code', 'ip_address')
    ordering = ('-accessed_at',)


@admin.register(Group)
class GroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'user__username')


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'user')
    search_fields = ('name', 'user__username')
