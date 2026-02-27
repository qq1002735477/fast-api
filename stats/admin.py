from django.contrib import admin
from .models import ExportTask


@admin.register(ExportTask)
class ExportTaskAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'created_at', 'completed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username',)
    ordering = ('-created_at',)
