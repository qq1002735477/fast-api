"""
Celery tasks for stats app.

Handles async export processing for large datasets.

Requirements: 12.2
"""
try:
    from celery import shared_task
except ImportError:
    # Celery not installed, create a dummy decorator
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_export_task(self, task_id: int):
    """
    Process an export task asynchronously.
    
    This task:
    1. Retrieves the export task from the database
    2. Generates the CSV file with all user link data
    3. Updates the task status upon completion or failure
    
    Args:
        task_id: The ID of the ExportTask to process.
    
    Returns:
        Dict with status and file path or error message.
    
    Requirements: 12.2
    """
    from .models import ExportTask
    from .export_service import export_service
    
    try:
        # Get the export task
        task = ExportTask.objects.get(id=task_id)
        
        # Check if task is still pending
        if task.status != 'pending':
            return {
                'status': 'skipped',
                'reason': f'Task is already {task.status}'
            }
        
        # Generate the CSV
        file_path = export_service.generate_csv(task.user, task)
        
        return {
            'status': 'success',
            'task_id': task_id,
            'file_path': file_path
        }
    
    except ExportTask.DoesNotExist:
        return {
            'status': 'error',
            'error': 'Export task not found'
        }
    
    except Exception as exc:
        # Update task status to failed
        try:
            task = ExportTask.objects.get(id=task_id)
            task.status = 'failed'
            task.error_message = str(exc)
            task.save(update_fields=['status', 'error_message'])
        except ExportTask.DoesNotExist:
            pass
        
        # Retry on failure
        raise self.retry(exc=exc)


@shared_task
def cleanup_old_export_files(days: int = 7):
    """
    Periodic task to clean up old export files.
    
    Deletes export files older than the specified number of days.
    
    Args:
        days: Number of days after which to delete files.
    
    Returns:
        Dict with cleanup statistics.
    """
    import os
    from datetime import timedelta
    from django.utils import timezone
    from .models import ExportTask
    from .export_service import export_service
    
    cutoff_date = timezone.now() - timedelta(days=days)
    
    # Find old completed tasks
    old_tasks = ExportTask.objects.filter(
        status='completed',
        completed_at__lt=cutoff_date
    )
    
    deleted_count = 0
    for task in old_tasks:
        if export_service.delete_export_file(task):
            deleted_count += 1
        # Clear the file path
        task.file_path = ''
        task.save(update_fields=['file_path'])
    
    return {
        'status': 'success',
        'deleted_count': deleted_count,
        'tasks_processed': old_tasks.count()
    }
