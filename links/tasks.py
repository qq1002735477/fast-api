"""
Celery tasks for asynchronous link operations.

Handles access recording and click count updates.
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

from django.db import transaction
from django.db.models import F


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def record_link_access(self, link_id: int, ip_address: str, user_agent: str, referer: str = ''):
    """
    Record a link access asynchronously.
    
    This task:
    1. Increments the click count on the Link model
    2. Creates an AccessLog entry with visitor details
    
    Args:
        link_id: The ID of the link that was accessed.
        ip_address: The visitor's IP address.
        user_agent: The visitor's User-Agent string.
        referer: The referring URL (optional).
    
    Requirements: 3.4, 3.5
    """
    from .models import Link, AccessLog
    
    try:
        with transaction.atomic():
            # Increment click count using F() to avoid race conditions
            updated = Link.objects.filter(id=link_id).update(
                click_count=F('click_count') + 1
            )
            
            if updated == 0:
                # Link doesn't exist, nothing to do
                return {'status': 'skipped', 'reason': 'link_not_found'}
            
            # Create access log entry
            AccessLog.objects.create(
                link_id=link_id,
                ip_address=ip_address,
                user_agent=user_agent[:512],  # Truncate to max length
                referer=referer[:2048] if referer else '',  # Truncate to max length
            )
        
        return {'status': 'success', 'link_id': link_id}
    
    except Exception as exc:
        # Retry on failure
        raise self.retry(exc=exc)


@shared_task
def bulk_update_click_counts(updates: dict):
    """
    Bulk update click counts for multiple links.
    
    Used for batch processing of click count updates from a buffer.
    
    Args:
        updates: Dict mapping link_id to click count increment.
    """
    from .models import Link
    
    for link_id, increment in updates.items():
        Link.objects.filter(id=link_id).update(
            click_count=F('click_count') + increment
        )
    
    return {'status': 'success', 'updated_count': len(updates)}


@shared_task
def cleanup_expired_links_cache():
    """
    Periodic task to clean up cached data for expired links.
    
    This task should be scheduled to run periodically (e.g., every hour).
    
    Requirements: 8.3
    """
    from django.utils import timezone
    from .models import Link
    from .services import link_cache_service
    
    # Find recently expired links
    expired_links = Link.objects.filter(
        expires_at__lte=timezone.now(),
        is_active=True
    ).values_list('short_code', flat=True)
    
    # Invalidate cache for each expired link
    deleted_count = 0
    for short_code in expired_links:
        if link_cache_service.delete(short_code):
            deleted_count += 1
    
    return {'status': 'success', 'deleted_count': deleted_count}


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def batch_create_links_async(self, user_id: int, links_data: list):
    """
    Asynchronously create multiple short links.
    
    Used when batch creation request contains more than 10 items.
    
    Args:
        user_id: The ID of the user creating the links.
        links_data: List of link data dictionaries.
    
    Returns:
        Dict with results for each link creation attempt.
    
    Requirements: 9.1, 9.2, 9.4
    """
    from django.contrib.auth import get_user_model
    from django.utils import timezone
    from django.core.validators import URLValidator
    from django.core.exceptions import ValidationError as DjangoValidationError
    from .models import Link, Group, Tag
    from .services import short_code_generator
    from .security import url_security_service
    
    User = get_user_model()
    url_validator = URLValidator()
    
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return {
            'status': 'error',
            'error': 'User not found',
            'results': []
        }
    
    results = []
    successful = 0
    failed = 0
    
    for index, link_data in enumerate(links_data):
        try:
            original_url = link_data.get('original_url')
            custom_code = link_data.get('custom_code')
            expires_at_str = link_data.get('expires_at')
            group_id = link_data.get('group_id')
            tag_ids = link_data.get('tag_ids', [])
            
            # Validate URL format
            try:
                url_validator(original_url)
            except DjangoValidationError:
                results.append({
                    'index': index,
                    'success': False,
                    'short_code': None,
                    'original_url': original_url,
                    'error': 'Invalid URL format'
                })
                failed += 1
                continue
            
            # Check URL security (malicious domain blacklist)
            safety_check = url_security_service.check_url_safety(original_url)
            if not safety_check['is_safe']:
                results.append({
                    'index': index,
                    'success': False,
                    'short_code': None,
                    'original_url': original_url,
                    'error': f"URL rejected: {safety_check['reason']}"
                })
                failed += 1
                continue
            
            # Parse expires_at if provided
            expires_at = None
            if expires_at_str:
                from datetime import datetime
                if isinstance(expires_at_str, str):
                    expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
                else:
                    expires_at = expires_at_str
            
            # Check for existing link with same URL (idempotency)
            existing_link = Link.objects.filter(
                user=user,
                original_url=original_url
            ).first()
            
            if existing_link:
                results.append({
                    'index': index,
                    'success': True,
                    'short_code': existing_link.short_code,
                    'original_url': original_url,
                    'error': None
                })
                successful += 1
                continue
            
            # Validate custom code if provided
            if custom_code:
                if not short_code_generator.validate(custom_code):
                    results.append({
                        'index': index,
                        'success': False,
                        'short_code': None,
                        'original_url': original_url,
                        'error': 'Invalid custom code format'
                    })
                    failed += 1
                    continue
                
                if not short_code_generator.is_available(custom_code):
                    results.append({
                        'index': index,
                        'success': False,
                        'short_code': None,
                        'original_url': original_url,
                        'error': 'Custom code already in use'
                    })
                    failed += 1
                    continue
                
                short_code = custom_code
            else:
                short_code = short_code_generator.generate_unique()
            
            # Validate group if provided
            if group_id:
                if not Group.objects.filter(id=group_id, user=user).exists():
                    results.append({
                        'index': index,
                        'success': False,
                        'short_code': None,
                        'original_url': original_url,
                        'error': 'Group not found or does not belong to you'
                    })
                    failed += 1
                    continue
            
            # Validate tags if provided
            if tag_ids:
                existing_tags = Tag.objects.filter(id__in=tag_ids, user=user)
                if existing_tags.count() != len(tag_ids):
                    results.append({
                        'index': index,
                        'success': False,
                        'short_code': None,
                        'original_url': original_url,
                        'error': 'One or more tags not found'
                    })
                    failed += 1
                    continue
            
            # Create the link
            link = Link.objects.create(
                short_code=short_code,
                original_url=original_url,
                user=user,
                group_id=group_id,
                expires_at=expires_at
            )
            
            # Add tags if provided
            if tag_ids:
                link.tags.set(tag_ids)
            
            results.append({
                'index': index,
                'success': True,
                'short_code': short_code,
                'original_url': original_url,
                'error': None
            })
            successful += 1
            
        except Exception as e:
            results.append({
                'index': index,
                'success': False,
                'short_code': None,
                'original_url': link_data.get('original_url'),
                'error': str(e)
            })
            failed += 1
    
    return {
        'status': 'completed',
        'total': len(links_data),
        'successful': successful,
        'failed': failed,
        'results': results
    }
