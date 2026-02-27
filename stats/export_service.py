"""
Export service for generating CSV exports of user link data.

Provides functionality for:
- Generating CSV files with link data and statistics
- Async export processing via Celery
- File management for export downloads

Requirements: 12.1, 12.2, 12.3
"""
import csv
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

from django.conf import settings
from django.utils import timezone
from django.db.models import Count

from links.models import Link, AccessLog
from .models import ExportTask


class ExportService:
    """
    Service for exporting user link data to CSV files.
    
    Handles:
    - CSV generation with link details, statistics, and tags
    - File storage management
    - Export task status tracking
    """
    
    def __init__(self):
        self.export_dir = getattr(settings, 'EXPORT_FILE_PATH', Path(settings.BASE_DIR) / 'exports')
        # Ensure export directory exists
        os.makedirs(self.export_dir, exist_ok=True)
    
    def create_export_task(self, user) -> ExportTask:
        """
        Create a new export task for a user.
        
        Args:
            user: The user requesting the export.
        
        Returns:
            The created ExportTask instance.
        """
        # Count user's links for progress tracking
        total_links = Link.objects.filter(user=user).count()
        
        task = ExportTask.objects.create(
            user=user,
            status='pending',
            total_links=total_links
        )
        return task

    def generate_csv(self, user, task: ExportTask) -> str:
        """
        Generate a CSV file containing all link data for a user.
        
        The CSV includes:
        - short_code: The short code
        - original_url: The original URL
        - created_at: Link creation date
        - expires_at: Link expiration date (if set)
        - click_count: Total click count
        - unique_visitors: Number of unique visitors
        - tags: Comma-separated list of tag names
        - group_name: Name of the group (if assigned)
        - is_active: Whether the link is active
        
        Args:
            user: The user whose data to export.
            task: The ExportTask to update with progress.
        
        Returns:
            The file path of the generated CSV.
        
        Requirements: 12.1, 12.3
        """
        # Generate unique filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = str(uuid.uuid4())[:8]
        filename = f'export_{user.id}_{timestamp}_{unique_id}.csv'
        file_path = os.path.join(self.export_dir, filename)
        
        # Update task status to processing
        task.status = 'processing'
        task.save(update_fields=['status'])
        
        try:
            # Get all links for the user with related data
            links = Link.objects.filter(user=user).select_related(
                'group'
            ).prefetch_related('tags').order_by('-created_at')
            
            # Write CSV file
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = [
                    'short_code',
                    'original_url',
                    'created_at',
                    'expires_at',
                    'click_count',
                    'unique_visitors',
                    'tags',
                    'group_name',
                    'is_active'
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for link in links:
                    # Get unique visitors count for this link
                    unique_visitors = AccessLog.objects.filter(
                        link=link
                    ).values('ip_address').distinct().count()
                    
                    # Get tag names as comma-separated string
                    tag_names = ','.join([tag.name for tag in link.tags.all()])
                    
                    # Get group name
                    group_name = link.group.name if link.group else ''
                    
                    writer.writerow({
                        'short_code': link.short_code,
                        'original_url': link.original_url,
                        'created_at': link.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                        'expires_at': link.expires_at.strftime('%Y-%m-%d %H:%M:%S') if link.expires_at else '',
                        'click_count': link.click_count,
                        'unique_visitors': unique_visitors,
                        'tags': tag_names,
                        'group_name': group_name,
                        'is_active': 'Yes' if link.is_active else 'No'
                    })
            
            # Update task with success
            task.status = 'completed'
            task.file_path = file_path
            task.completed_at = timezone.now()
            task.save(update_fields=['status', 'file_path', 'completed_at'])
            
            return file_path
            
        except Exception as e:
            # Update task with failure
            task.status = 'failed'
            task.error_message = str(e)
            task.completed_at = timezone.now()
            task.save(update_fields=['status', 'error_message', 'completed_at'])
            raise
    
    def get_export_task(self, task_id: int, user) -> Optional[ExportTask]:
        """
        Get an export task by ID for a specific user.
        
        Args:
            task_id: The ID of the export task.
            user: The user who owns the task.
        
        Returns:
            The ExportTask if found and owned by user, None otherwise.
        """
        try:
            return ExportTask.objects.get(id=task_id, user=user)
        except ExportTask.DoesNotExist:
            return None
    
    def get_file_path(self, task: ExportTask) -> Optional[str]:
        """
        Get the file path for a completed export task.
        
        Args:
            task: The ExportTask instance.
        
        Returns:
            The file path if export is completed and file exists, None otherwise.
        """
        if task.status != 'completed' or not task.file_path:
            return None
        
        if os.path.exists(task.file_path):
            return task.file_path
        
        return None
    
    def delete_export_file(self, task: ExportTask) -> bool:
        """
        Delete the export file for a task.
        
        Args:
            task: The ExportTask instance.
        
        Returns:
            True if file was deleted, False otherwise.
        """
        if task.file_path and os.path.exists(task.file_path):
            try:
                os.remove(task.file_path)
                return True
            except OSError:
                return False
        return False
    
    def get_user_export_tasks(self, user, limit: int = 10) -> List[ExportTask]:
        """
        Get recent export tasks for a user.
        
        Args:
            user: The user whose tasks to retrieve.
            limit: Maximum number of tasks to return.
        
        Returns:
            List of ExportTask instances.
        """
        return list(ExportTask.objects.filter(user=user).order_by('-created_at')[:limit])


# Singleton instance for convenience
export_service = ExportService()
