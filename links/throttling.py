"""
Custom DRF throttle classes for rate limiting.

Provides throttle classes that integrate with the RateLimitService
and add quota information to response headers.

Requirements: 6.1, 6.4
"""
import time
from typing import Optional

from django.conf import settings
from rest_framework.throttling import BaseThrottle
from rest_framework.request import Request

from .ratelimit import rate_limit_service


class SlidingWindowThrottle(BaseThrottle):
    """
    Custom throttle class using sliding window algorithm.
    
    Features:
    - Uses Redis-based sliding window rate limiting
    - Different limits for authenticated (100/min) vs anonymous (20/min) users
    - Adds rate limit headers to responses
    - Returns 429 with retry-after header when limit exceeded
    
    Response Headers:
    - X-RateLimit-Limit: Total requests allowed per window
    - X-RateLimit-Remaining: Requests remaining in current window
    - X-RateLimit-Reset: Seconds until window resets
    - Retry-After: Seconds to wait before retrying (only on 429)
    """
    
    # Store quota info for adding to response headers
    _quota_info = {}
    
    def __init__(self):
        """Initialize throttle with rate limit service."""
        self.service = rate_limit_service
        self._wait_time = None
    
    def allow_request(self, request: Request, view) -> bool:
        """
        Check if the request should be allowed.
        
        Args:
            request: DRF request object.
            view: The view being accessed.
        
        Returns:
            True if request is allowed, False if rate limited.
        """
        # Check rate limit
        is_allowed, remaining, limit, reset_time = self.service.check_rate_limit(
            request
        )
        
        # Store wait time for the wait() method
        self._wait_time = reset_time
        
        # Store quota info for response headers
        # Use request as key to handle concurrent requests
        request._ratelimit_info = {
            'limit': limit,
            'remaining': remaining,
            'reset': reset_time,
            'allowed': is_allowed,
        }
        
        return is_allowed
    
    def wait(self) -> Optional[float]:
        """
        Return the number of seconds to wait before retrying.
        
        Returns:
            Seconds to wait, or None if no wait needed.
        """
        # Return the stored wait time from the last check
        return self._wait_time if self._wait_time else self.service.window_size
    
    def get_ident(self, request: Request) -> str:
        """
        Get identifier for the request.
        
        Args:
            request: DRF request object.
        
        Returns:
            Identifier string (user ID or IP).
        """
        return self.service._get_identifier(request)


class AuthenticatedUserThrottle(SlidingWindowThrottle):
    """
    Throttle class specifically for authenticated users.
    
    Rate limit: 100 requests per minute (configurable via settings).
    """
    scope = 'authenticated'
    
    def allow_request(self, request: Request, view) -> bool:
        """Only apply to authenticated users."""
        if not (hasattr(request, 'user') and request.user.is_authenticated):
            return True
        return super().allow_request(request, view)


class AnonymousUserThrottle(SlidingWindowThrottle):
    """
    Throttle class specifically for anonymous users.
    
    Rate limit: 20 requests per minute (configurable via settings).
    """
    scope = 'anonymous'
    
    def allow_request(self, request: Request, view) -> bool:
        """Only apply to anonymous users."""
        if hasattr(request, 'user') and request.user.is_authenticated:
            return True
        return super().allow_request(request, view)


def add_ratelimit_headers(response, request):
    """
    Add rate limit headers to response.
    
    Args:
        response: DRF response object.
        request: DRF request object.
    
    Returns:
        Response with rate limit headers added.
    """
    # Get rate limit info from request (set by throttle)
    ratelimit_info = getattr(request, '_ratelimit_info', None)
    
    if ratelimit_info:
        response['X-RateLimit-Limit'] = ratelimit_info['limit']
        response['X-RateLimit-Remaining'] = ratelimit_info['remaining']
        response['X-RateLimit-Reset'] = ratelimit_info['reset']
        
        # Add Retry-After header if rate limited
        if not ratelimit_info['allowed']:
            response['Retry-After'] = ratelimit_info['reset']
    
    return response
