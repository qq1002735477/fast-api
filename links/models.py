from django.db import models
from django.conf import settings


class Group(models.Model):
    """Link group model."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='link_groups',
        verbose_name='用户'
    )
    name = models.CharField(max_length=100, verbose_name='分组名称')
    description = models.TextField(blank=True, verbose_name='描述')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')

    class Meta:
        verbose_name = '分组'
        verbose_name_plural = '分组'
        db_table = 'groups'
        unique_together = ['user', 'name']

    def __str__(self):
        return self.name


class Tag(models.Model):
    """Link tag model."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tags',
        verbose_name='用户'
    )
    name = models.CharField(max_length=50, verbose_name='标签名称')

    class Meta:
        verbose_name = '标签'
        verbose_name_plural = '标签'
        db_table = 'tags'
        unique_together = ['user', 'name']

    def __str__(self):
        return self.name


class Link(models.Model):
    """Short link model."""
    short_code = models.CharField(
        max_length=10,
        unique=True,
        db_index=True,
        verbose_name='短码'
    )
    original_url = models.URLField(max_length=2048, verbose_name='原始链接')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='links',
        verbose_name='用户'
    )
    group = models.ForeignKey(
        Group,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='links',
        verbose_name='分组'
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='links', verbose_name='标签')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')
    expires_at = models.DateTimeField(null=True, blank=True, verbose_name='过期时间')
    click_count = models.PositiveIntegerField(default=0, verbose_name='点击次数')
    is_active = models.BooleanField(default=True, verbose_name='是否激活')

    class Meta:
        verbose_name = '短链接'
        verbose_name_plural = '短链接'
        db_table = 'links'
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['short_code']),
        ]

    def __str__(self):
        return f'{self.short_code} -> {self.original_url[:50]}'


class AccessLog(models.Model):
    """Access log model for tracking link visits."""
    link = models.ForeignKey(
        Link,
        on_delete=models.CASCADE,
        related_name='access_logs',
        verbose_name='链接'
    )
    ip_address = models.GenericIPAddressField(verbose_name='IP地址')
    user_agent = models.CharField(max_length=512, verbose_name='User-Agent')
    referer = models.URLField(max_length=2048, blank=True, verbose_name='来源页面')
    accessed_at = models.DateTimeField(auto_now_add=True, verbose_name='访问时间')

    class Meta:
        verbose_name = '访问日志'
        verbose_name_plural = '访问日志'
        db_table = 'access_logs'
        indexes = [
            models.Index(fields=['link', 'accessed_at']),
        ]

    def __str__(self):
        return f'{self.link.short_code} - {self.accessed_at}'
