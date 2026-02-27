"""
Serializers for the stats app.

Handles export task serialization for API responses.
"""
from rest_framework import serializers

from .models import ExportTask


class ExportTaskSerializer(serializers.ModelSerializer):
    """
    Serializer for ExportTask model.
    
    Used for displaying export task status and details.
    """
    
    class Meta:
        model = ExportTask
        fields = [
            'id',
            'status',
            'total_links',
            'error_message',
            'created_at',
            'completed_at'
        ]
        read_only_fields = [
            'id',
            'status',
            'total_links',
            'error_message',
            'created_at',
            'completed_at'
        ]


class ExportRequestSerializer(serializers.Serializer):
    """
    Serializer for export request.
    
    Currently empty as export doesn't require any input parameters,
    but can be extended to support filtering options in the future.
    """
    pass


class ExportStatusResponseSerializer(serializers.Serializer):
    """
    Serializer for export status response.
    """
    id = serializers.IntegerField(help_text='Export task ID')
    status = serializers.CharField(help_text='Task status: pending, processing, completed, failed')
    total_links = serializers.IntegerField(help_text='Total number of links to export')
    error_message = serializers.CharField(
        required=False, 
        allow_blank=True,
        help_text='Error message if task failed'
    )
    created_at = serializers.DateTimeField(help_text='Task creation timestamp')
    completed_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text='Task completion timestamp'
    )
    download_url = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='URL to download the export file (only when completed)'
    )
