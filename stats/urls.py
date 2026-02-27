"""
URL configuration for the stats app.

Provides export API endpoints.
"""
from django.urls import path

from .views import (
    ExportCreateView,
    ExportStatusView,
    ExportDownloadView,
    ExportListView
)

urlpatterns = [
    # Export endpoints
    path('export/', ExportListView.as_view(), name='export-list'),
    path('export/create/', ExportCreateView.as_view(), name='export-create'),
    path('export/<int:task_id>/', ExportStatusView.as_view(), name='export-status'),
    path('export/<int:task_id>/download/', ExportDownloadView.as_view(), name='export-download'),
]
