"""
Middleware for the links app.

Provides middleware for adding rate limit headers to responses.
"""
from django.utils.deprecation import MiddlewareMixin

from .ratelimit import rate_limit_service


class RateLimitHeadersMiddleware(MiddlewareMixin):
    """
    Middleware to add rate limit headers to all API responses.
    
    Adds the following headers:
    - X-RateLimit-Limit: Total requests allowed per window
    - X-RateLimit-Remaining: Requests remaining in current window
    - X-RateLimit-Reset: Seconds until window resets
    
    Requirements: 6.4
    """
    
    def process_response(self, request, response):
        """
        Add rate limit headers to response.
        
        Args:
            request: Django request object.
            response: Django response object.
        
        Returns:
            Response with rate limit headers added.
        """
        # Check if rate limit info was already set by throttle
        ratelimit_info = getattr(request, '_ratelimit_info', None)
        
        if ratelimit_info:
            # Use info from throttle
            response['X-RateLimit-Limit'] = str(ratelimit_info['limit'])
            response['X-RateLimit-Remaining'] = str(ratelimit_info['remaining'])
            response['X-RateLimit-Reset'] = str(ratelimit_info['reset'])
            
            # Add Retry-After header if rate limited
            if not ratelimit_info.get('allowed', True):
                response['Retry-After'] = str(ratelimit_info['reset'])
        elif request.path.startswith('/api/'):
            # Get quota info without incrementing (for non-throttled API endpoints)
            try:
                quota_info = rate_limit_service.get_quota_info(request)
                response['X-RateLimit-Limit'] = str(quota_info['limit'])
                response['X-RateLimit-Remaining'] = str(quota_info['remaining'])
                response['X-RateLimit-Reset'] = str(quota_info['reset'])
            except Exception:
                # If Redis is unavailable, skip headers
                pass
        
        return response
