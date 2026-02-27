"""
Short link services including short code generation, validation, and caching.
"""
import json
import re
import secrets
import string
from typing import Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from .models import Link


# Base62 character set: a-z, A-Z, 0-9
BASE62_CHARS = string.ascii_lowercase + string.ascii_uppercase + string.digits


class ShortCodeGenerator:
    """Service for generating and validating short codes."""
    
    def __init__(self):
        self.min_length = getattr(settings, 'SHORT_CODE_MIN_LENGTH', 4)
        self.max_length = getattr(settings, 'SHORT_CODE_MAX_LENGTH', 10)
        self.default_length = getattr(settings, 'SHORT_CODE_LENGTH', 6)
    
    def generate(self, length: Optional[int] = None) -> str:
        """
        Generate a random short code using Base62 characters.
        
        Args:
            length: Length of the short code. Defaults to settings.SHORT_CODE_LENGTH.
        
        Returns:
            A random short code string.
        """
        if length is None:
            length = self.default_length
        
        # Ensure length is within valid range
        length = max(self.min_length, min(length, self.max_length))
        
        return ''.join(secrets.choice(BASE62_CHARS) for _ in range(length))
    
    def validate(self, code: str) -> bool:
        """
        Validate that a short code meets format requirements.
        
        A valid short code:
        - Contains only Base62 characters (a-z, A-Z, 0-9)
        - Has length between min_length and max_length (4-10 characters)
        - Contains no whitespace
        
        Args:
            code: The short code to validate.
        
        Returns:
            True if valid, False otherwise.
        """
        if not code:
            return False
        
        # Check length
        if not (self.min_length <= len(code) <= self.max_length):
            return False
        
        # Check for whitespace
        if any(c.isspace() for c in code):
            return False
        
        # Check characters - must be Base62 only (a-z, A-Z, 0-9)
        pattern = r'^[a-zA-Z0-9]+$'
        return bool(re.match(pattern, code))
    
    def is_available(self, code: str) -> bool:
        """
        Check if a short code is available (not already in use).
        
        Args:
            code: The short code to check.
        
        Returns:
            True if available, False if already in use.
        """
        return not Link.objects.filter(short_code=code).exists()
    
    def generate_unique(self, length: Optional[int] = None, max_attempts: int = 10) -> str:
        """
        Generate a unique short code that doesn't exist in the database.
        
        Args:
            length: Length of the short code.
            max_attempts: Maximum number of generation attempts.
        
        Returns:
            A unique short code.
        
        Raises:
            RuntimeError: If unable to generate a unique code after max_attempts.
        """
        for _ in range(max_attempts):
            code = self.generate(length)
            if self.is_available(code):
                return code
        
        raise RuntimeError(
            f"Unable to generate unique short code after {max_attempts} attempts"
        )


# Singleton instance for convenience
short_code_generator = ShortCodeGenerator()


class LinkCacheService:
    """
    Service for caching short link data in Redis.
    
    Provides read/write operations for link cache with TTL-based expiration.
    Cache key format: link:{short_code}
    Cache value: JSON with original_url and expires_at
    """
    
    CACHE_KEY_PREFIX = 'link:'
    
    def __init__(self):
        self.default_ttl = getattr(settings, 'LINK_CACHE_TTL', 3600)  # 1 hour default
    
    def _get_cache_key(self, short_code: str) -> str:
        """Generate cache key for a short code."""
        return f'{self.CACHE_KEY_PREFIX}{short_code}'
    
    def get(self, short_code: str) -> Optional[dict]:
        """
        Get link data from cache.
        
        Args:
            short_code: The short code to look up.
        
        Returns:
            Dict with 'original_url' and 'expires_at' if found, None otherwise.
        """
        cache_key = self._get_cache_key(short_code)
        cached_data = cache.get(cache_key)
        
        if cached_data is None:
            return None
        
        # Parse JSON data
        try:
            return json.loads(cached_data)
        except (json.JSONDecodeError, TypeError):
            # Invalid cache data, delete it
            self.delete(short_code)
            return None
    
    def set(self, short_code: str, original_url: str, expires_at=None, link_id: int = None, ttl: Optional[int] = None) -> bool:
        """
        Store link data in cache.
        
        Args:
            short_code: The short code.
            original_url: The original URL to redirect to.
            expires_at: Optional expiration datetime for the link.
            link_id: The database ID of the link (for access recording).
            ttl: Optional TTL in seconds. Defaults to LINK_CACHE_TTL.
        
        Returns:
            True if successfully cached, False otherwise.
        """
        cache_key = self._get_cache_key(short_code)
        
        # Prepare cache data
        cache_data = {
            'original_url': original_url,
            'expires_at': expires_at.isoformat() if expires_at else None,
            'link_id': link_id,
        }
        
        # Calculate TTL
        if ttl is None:
            ttl = self.default_ttl
            
            # If link has expiration, adjust TTL to not exceed it
            if expires_at:
                now = timezone.now()
                if expires_at > now:
                    seconds_until_expiry = int((expires_at - now).total_seconds())
                    ttl = min(ttl, seconds_until_expiry)
                else:
                    # Link already expired, don't cache
                    return False
        
        try:
            cache.set(cache_key, json.dumps(cache_data), timeout=ttl)
            return True
        except Exception:
            return False
    
    def delete(self, short_code: str) -> bool:
        """
        Remove link data from cache (cache invalidation).
        
        Args:
            short_code: The short code to remove from cache.
        
        Returns:
            True if deleted, False otherwise.
        """
        cache_key = self._get_cache_key(short_code)
        try:
            cache.delete(cache_key)
            return True
        except Exception:
            return False
    
    def get_or_fetch(self, short_code: str) -> Tuple[Optional[dict], bool]:
        """
        Get link data from cache, or fetch from database if not cached.
        
        Args:
            short_code: The short code to look up.
        
        Returns:
            Tuple of (link_data, from_cache) where:
            - link_data: Dict with 'original_url', 'expires_at', 'is_active', 'link_id' or None
            - from_cache: True if data came from cache, False if from database
        """
        # Try cache first
        cached_data = self.get(short_code)
        if cached_data is not None:
            return cached_data, True
        
        # Fetch from database
        try:
            link = Link.objects.get(short_code=short_code)
        except Link.DoesNotExist:
            return None, False
        
        # Prepare link data
        link_data = {
            'original_url': link.original_url,
            'expires_at': link.expires_at.isoformat() if link.expires_at else None,
            'is_active': link.is_active,
            'link_id': link.id,
        }
        
        # Cache the data if link is active
        if link.is_active:
            self.set(short_code, link.original_url, link.expires_at, link.id)
        
        return link_data, False
    
    def is_expired(self, link_data: dict) -> bool:
        """
        Check if a link has expired based on its data.
        
        Args:
            link_data: Dict containing 'expires_at' key.
        
        Returns:
            True if expired, False otherwise.
        """
        expires_at_str = link_data.get('expires_at')
        if not expires_at_str:
            return False
        
        try:
            from datetime import datetime
            expires_at = datetime.fromisoformat(expires_at_str)
            # Make timezone-aware if needed
            if expires_at.tzinfo is None:
                from django.utils import timezone as tz
                expires_at = tz.make_aware(expires_at)
            return expires_at <= timezone.now()
        except (ValueError, TypeError):
            return False


# Singleton instance for convenience
link_cache_service = LinkCacheService()
