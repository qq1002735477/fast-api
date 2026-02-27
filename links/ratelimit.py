"""
Rate limiting service using Redis sliding window algorithm.

Provides rate limiting functionality for API endpoints with different
limits for authenticated and anonymous users.

Requirements: 6.2, 6.3
"""
import time
from typing import Tuple, Optional

from django.conf import settings
from django.core.cache import cache


class RateLimitService:
    """
    Service for rate limiting using Redis sliding window algorithm.
    
    Implements a sliding window rate limiter that:
    - Uses Redis for distributed rate limiting
    - Supports different limits for authenticated vs anonymous users
    - Returns remaining quota and reset time information
    
    Cache key format: ratelimit:{identifier}:{window}
    """
    
    # Default rate limits (requests per minute)
    DEFAULT_AUTHENTICATED_LIMIT = 100
    DEFAULT_ANONYMOUS_LIMIT = 20
    
    # Window size in seconds (1 minute)
    WINDOW_SIZE = 60
    
    # Cache key prefix
    CACHE_KEY_PREFIX = 'ratelimit:'
    
    def __init__(self):
        """Initialize rate limit service with settings."""
        self.authenticated_limit = getattr(
            settings, 'RATE_LIMIT_AUTHENTICATED', 
            self.DEFAULT_AUTHENTICATED_LIMIT
        )
        self.anonymous_limit = getattr(
            settings, 'RATE_LIMIT_ANONYMOUS',
            self.DEFAULT_ANONYMOUS_LIMIT
        )
        self.window_size = getattr(
            settings, 'RATE_LIMIT_WINDOW',
            self.WINDOW_SIZE
        )
    
    def _get_cache_key(self, identifier: str) -> str:
        """
        Generate cache key for rate limiting.
        
        Args:
            identifier: User ID for authenticated users, IP for anonymous.
        
        Returns:
            Cache key string.
        """
        # Use current window timestamp (floored to window size)
        current_window = int(time.time() // self.window_size)
        return f'{self.CACHE_KEY_PREFIX}{identifier}:{current_window}'
    
    def _get_identifier(self, request) -> str:
        """
        Get identifier for rate limiting from request.
        
        Args:
            request: Django request object.
        
        Returns:
            User ID for authenticated users, IP address for anonymous.
        """
        if hasattr(request, 'user') and request.user.is_authenticated:
            return f'user:{request.user.id}'
        
        # Get IP address from request
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', 'unknown')
        
        return f'anon:{ip}'
    
    def _get_limit(self, is_authenticated: bool) -> int:
        """
        Get rate limit based on authentication status.
        
        Args:
            is_authenticated: Whether the user is authenticated.
        
        Returns:
            Rate limit (requests per window).
        """
        return self.authenticated_limit if is_authenticated else self.anonymous_limit
    
    def check_rate_limit(
        self, 
        request,
        identifier: Optional[str] = None
    ) -> Tuple[bool, int, int, int]:
        """
        Check if request is within rate limit using sliding window.
        
        Args:
            request: Django request object.
            identifier: Optional custom identifier (defaults to user/IP based).
        
        Returns:
            Tuple of (is_allowed, remaining, limit, reset_time):
            - is_allowed: True if request is within limit
            - remaining: Number of requests remaining in window
            - limit: Total limit for this user type
            - reset_time: Seconds until window resets
        """
        if identifier is None:
            identifier = self._get_identifier(request)
        
        is_authenticated = (
            hasattr(request, 'user') and 
            request.user.is_authenticated
        )
        limit = self._get_limit(is_authenticated)
        
        cache_key = self._get_cache_key(identifier)
        
        # Get current count
        current_count = cache.get(cache_key, 0)
        
        # Calculate reset time (seconds until window ends)
        current_time = time.time()
        window_start = int(current_time // self.window_size) * self.window_size
        reset_time = int(window_start + self.window_size - current_time)
        
        # Check if within limit
        if current_count >= limit:
            remaining = 0
            is_allowed = False
        else:
            remaining = limit - current_count - 1  # -1 for current request
            is_allowed = True
            
            # Increment counter
            try:
                # Use atomic increment if available
                new_count = cache.incr(cache_key)
            except ValueError:
                # Key doesn't exist, set it
                cache.set(cache_key, 1, timeout=self.window_size)
                new_count = 1
            
            remaining = max(0, limit - new_count)
        
        return is_allowed, remaining, limit, reset_time
    
    def get_quota_info(self, request) -> dict:
        """
        Get current quota information without incrementing counter.
        
        Args:
            request: Django request object.
        
        Returns:
            Dict with quota information.
        """
        identifier = self._get_identifier(request)
        is_authenticated = (
            hasattr(request, 'user') and 
            request.user.is_authenticated
        )
        limit = self._get_limit(is_authenticated)
        
        cache_key = self._get_cache_key(identifier)
        current_count = cache.get(cache_key, 0)
        
        # Calculate reset time
        current_time = time.time()
        window_start = int(current_time // self.window_size) * self.window_size
        reset_time = int(window_start + self.window_size - current_time)
        
        remaining = max(0, limit - current_count)
        
        return {
            'limit': limit,
            'remaining': remaining,
            'reset': reset_time,
            'used': current_count,
        }
    
    def reset_limit(self, request) -> bool:
        """
        Reset rate limit for a request (for testing purposes).
        
        Args:
            request: Django request object.
        
        Returns:
            True if reset successful.
        """
        identifier = self._get_identifier(request)
        cache_key = self._get_cache_key(identifier)
        
        try:
            cache.delete(cache_key)
            return True
        except Exception:
            return False


# Singleton instance for convenience
rate_limit_service = RateLimitService()
