"""
Redirect views for short links.

Implements the GET /r/{short_code} endpoint with Redis caching.
"""
from django.http import HttpResponseRedirect
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

from .services import link_cache_service


@extend_schema(
    tags=['重定向'],
    summary="短链接重定向",
    description="""
访问短链接，重定向到原始 URL。

### 缓存策略
- 优先从 Redis 缓存查询
- 缓存未命中时查询数据库并缓存结果

### 访问记录
每次访问会异步记录：
- 访问时间
- 访问者 IP
- User-Agent

### 错误情况
- 404: 短链接不存在
- 410: 短链接已过期
    """,
    responses={
        302: OpenApiResponse(description="重定向到原始 URL"),
        404: OpenApiResponse(
            description="链接不存在",
            examples=[
                OpenApiExample(
                    '链接不存在',
                    value={
                        'error': {
                            'code': 'LINK_NOT_FOUND',
                            'message': 'Short link not found'
                        }
                    }
                )
            ]
        ),
        410: OpenApiResponse(
            description="链接已过期",
            examples=[
                OpenApiExample(
                    '链接已过期',
                    value={
                        'error': {
                            'code': 'LINK_EXPIRED',
                            'message': 'This link has expired'
                        }
                    }
                )
            ]
        ),
    }
)
@api_view(['GET'])
@permission_classes([AllowAny])
def redirect_to_original(request, short_code):
    """
    Redirect to the original URL for a given short code.
    
    Requirements: 3.1, 3.2, 3.3, 8.2
    """
    # Get link data from cache or database
    link_data, from_cache = link_cache_service.get_or_fetch(short_code)
    
    # Link not found
    if link_data is None:
        return Response(
            {'error': {'code': 'LINK_NOT_FOUND', 'message': 'Short link not found'}},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Check if link is active (only available from DB fetch)
    if not link_data.get('is_active', True):
        return Response(
            {'error': {'code': 'LINK_NOT_FOUND', 'message': 'Short link not found'}},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Check if link has expired
    if link_cache_service.is_expired(link_data):
        # Invalidate cache for expired link
        link_cache_service.delete(short_code)
        return Response(
            {'error': {'code': 'LINK_EXPIRED', 'message': 'This link has expired'}},
            status=status.HTTP_410_GONE
        )
    
    # Get client info for access logging (will be used by async task)
    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:512]
    referer = request.META.get('HTTP_REFERER', '')[:2048]
    
    # Trigger async access recording if link_id is available
    link_id = link_data.get('link_id')
    if link_id:
        try:
            from .tasks import record_link_access
            result = record_link_access.delay(link_id, ip_address, user_agent, referer)
            if hasattr(result, 'get'):
                try:
                    result.get(timeout=1)
                except Exception:
                    pass
        except ImportError:
            _record_access_sync(link_id, ip_address, user_agent, referer)
        except Exception:
            try:
                _record_access_sync(link_id, ip_address, user_agent, referer)
            except Exception:
                pass
    
    # Return redirect response
    return HttpResponseRedirect(link_data['original_url'])


def get_client_ip(request):
    """
    Extract client IP address from request.
    
    Handles X-Forwarded-For header for proxied requests.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
    return ip



def _record_access_sync(link_id: int, ip_address: str, user_agent: str, referer: str = ''):
    """
    Record link access synchronously (fallback when Celery is not available).
    
    Args:
        link_id: The ID of the link that was accessed.
        ip_address: The visitor's IP address.
        user_agent: The visitor's User-Agent string.
        referer: The referring URL (optional).
    """
    from django.db import transaction
    from django.db.models import F
    from .models import Link, AccessLog
    
    try:
        with transaction.atomic():
            # Increment click count
            Link.objects.filter(id=link_id).update(
                click_count=F('click_count') + 1
            )
            
            # Create access log entry
            AccessLog.objects.create(
                link_id=link_id,
                ip_address=ip_address,
                user_agent=user_agent[:512],
                referer=referer[:2048] if referer else '',
            )
    except Exception:
        # Don't fail redirect if access recording fails
        pass
