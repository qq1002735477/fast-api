from django.db import models
from django.conf import settings


class ExportTask(models.Model):
    """
    Export task model for async data export.
    
    Tracks the status and progress of user data export requests.
    Supports async processing via Celery for large datasets.
    
    Requirements: 12.2
    """
    STATUS_CHOICES = [
        ('pending', '等待中'),
        ('processing', '处理中'),
        ('completed', '已完成'),
        ('failed', '失败'),
    ]
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='export_tasks',
        verbose_name='用户'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='状态'
    )
    file_path = models.CharField(max_length=255, blank=True, verbose_name='文件路径')
    total_links = models.PositiveIntegerField(default=0, verbose_name='总链接数')
    error_message = models.TextField(blank=True, verbose_name='错误信息')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name='完成时间')

    class Meta:
        verbose_name = '导出任务'
        verbose_name_plural = '导出任务'
        db_table = 'export_tasks'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.user.username} - {self.status} - {self.created_at}'
    
    @property
    def is_completed(self) -> bool:
        """Check if the export task is completed."""
        return self.status == 'completed'
    
    @property
    def is_failed(self) -> bool:
        """Check if the export task failed."""
        return self.status == 'failed'
    
    @property
    def is_pending(self) -> bool:
        """Check if the export task is pending."""
        return self.status == 'pending'
    
    @property
    def is_processing(self) -> bool:
        """Check if the export task is processing."""
        return self.status == 'processing'
