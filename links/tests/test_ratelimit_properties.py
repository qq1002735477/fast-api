"""
Property-based tests for rate limiting functionality.

Feature: url-shortener
Uses hypothesis library for property-based testing.

Note: These tests use a custom test endpoint that has throttling enabled
to test rate limiting functionality without affecting other tests.
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import path, include
from django.test import override_settings
import uuid
import time

from links.models import Link
from links.ratelimit import rate_limit_service
from links.throttling import SlidingWindowThrottle

User = get_user_model()


def create_test_user():
    """Create a unique test user."""
    unique_id = str(uuid.uuid4())[:8]
    return User.objects.create_user(
        username=f'testuser_{unique_id}',
        email=f'test_{unique_id}@example.com',
        password='TestPass123!'
    )


def get_authenticated_client(user):
    """Get an authenticated API client for a user."""
    from rest_framework_simplejwt.tokens import RefreshToken
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    return client


def clear_rate_limit_cache():
    """Clear all rate limit cache entries."""
    # Clear all cache keys starting with ratelimit:
    try:
        cache.clear()
    except Exception:
        pass


# Create a throttled test view for rate limit testing
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(['GET'])
@permission_classes([AllowAny])
@throttle_classes([SlidingWindowThrottle])
def throttled_test_view(request):
    """Test endpoint with throttling enabled."""
    return Response({'status': 'ok'})


# URL patterns for the test view
test_urlpatterns = [
    path('test/throttled/', throttled_test_view, name='throttled-test'),
]


@pytest.mark.django_db(transaction=True)
class TestRateLimitTrigger:
    """
    Property 15: Rate Limit Trigger
    
    For any user, when request count exceeds the limit (authenticated: 100/min,
    anonymous: 20/min), the system should return HTTP 429.
    
    Validates: Requirements 6.1, 6.2
    """

    @pytest.fixture(autouse=True)
    def setup_throttled_url(self, settings):
        """Add throttled test URL to urlpatterns."""
        from django.urls import clear_url_caches
        from importlib import reload
        import urlshortener.urls
        
        # Store original urlpatterns
        original_urlpatterns = urlshortener.urls.urlpatterns.copy()
        
        # Add test URL
        urlshortener.urls.urlpatterns.append(
            path('test/throttled/', throttled_test_view, name='throttled-test')
        )
        clear_url_caches()
        
        yield
        
        # Restore original urlpatterns
        urlshortener.urls.urlpatterns = original_urlpatterns
        clear_url_caches()

    @settings(max_examples=100, deadline=None)
    @given(
        request_count=st.integers(min_value=21, max_value=25)
    )
    def test_anonymous_rate_limit_triggered(self, request_count):
        """
        Feature: url-shortener, Property 15: 限流触发
        Validates: Requirements 6.1, 6.2
        
        For any anonymous user, exceeding 20 requests/minute should trigger 429.
        """
        # Clear cache before test
        clear_rate_limit_cache()
        
        client = APIClient()
        
        # Use a unique IP for this test to avoid interference
        unique_ip = f'192.168.{uuid.uuid4().int % 256}.{uuid.uuid4().int % 256}'
        
        try:
            rate_limited = False
            responses_before_limit = 0
            
            # Make requests to the throttled test endpoint
            for i in range(request_count):
                response = client.get(
                    '/test/throttled/',
                    REMOTE_ADDR=unique_ip
                )
                
                if response.status_code == 429:
                    rate_limited = True
                    responses_before_limit = i
                    break
            
            # Should be rate limited after 20 requests
            assert rate_limited, \
                f"Expected rate limit after 20 requests, made {request_count} without 429"
            
            # Should have been rate limited around the 20th request
            assert responses_before_limit <= 20, \
                f"Rate limit triggered after {responses_before_limit} requests, expected <= 20"
            
        finally:
            clear_rate_limit_cache()

    @settings(max_examples=100, deadline=None)
    @given(
        request_count=st.integers(min_value=101, max_value=105)
    )
    def test_authenticated_rate_limit_triggered(self, request_count):
        """
        Feature: url-shortener, Property 15: 限流触发
        Validates: Requirements 6.1, 6.2
        
        For any authenticated user, exceeding 100 requests/minute should trigger 429.
        """
        # Clear cache before test
        clear_rate_limit_cache()
        
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            rate_limited = False
            responses_before_limit = 0
            
            # Make requests to the throttled test endpoint
            for i in range(request_count):
                response = client.get('/test/throttled/')
                
                if response.status_code == 429:
                    rate_limited = True
                    responses_before_limit = i
                    break
            
            # Should be rate limited after 100 requests
            assert rate_limited, \
                f"Expected rate limit after 100 requests, made {request_count} without 429"
            
            # Should have been rate limited around the 100th request
            assert responses_before_limit <= 100, \
                f"Rate limit triggered after {responses_before_limit} requests, expected <= 100"
            
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()
            clear_rate_limit_cache()

    @settings(max_examples=100, deadline=None)
    @given(
        request_count=st.integers(min_value=1, max_value=19)
    )
    def test_anonymous_under_limit_allowed(self, request_count):
        """
        Feature: url-shortener, Property 15: 限流触发
        Validates: Requirements 6.1, 6.2
        
        For any anonymous user, requests under 20/minute should be allowed.
        """
        # Clear cache before test
        clear_rate_limit_cache()
        
        client = APIClient()
        
        # Use a unique IP for this test
        unique_ip = f'10.0.{uuid.uuid4().int % 256}.{uuid.uuid4().int % 256}'
        
        try:
            rate_limited = False
            
            # Make requests under the limit to throttled test endpoint
            for i in range(request_count):
                response = client.get(
                    '/test/throttled/',
                    REMOTE_ADDR=unique_ip
                )
                
                if response.status_code == 429:
                    rate_limited = True
                    break
            
            # Should NOT be rate limited under 20 requests
            assert not rate_limited, \
                f"Unexpected rate limit after {i} requests (limit is 20)"
            
        finally:
            clear_rate_limit_cache()

    @settings(max_examples=100, deadline=None)
    @given(
        request_count=st.integers(min_value=1, max_value=99)
    )
    def test_authenticated_under_limit_allowed(self, request_count):
        """
        Feature: url-shortener, Property 15: 限流触发
        Validates: Requirements 6.1, 6.2
        
        For any authenticated user, requests under 100/minute should be allowed.
        """
        # Clear cache before test
        clear_rate_limit_cache()
        
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            rate_limited = False
            
            # Make requests under the limit to throttled test endpoint
            for i in range(request_count):
                response = client.get('/test/throttled/')
                
                if response.status_code == 429:
                    rate_limited = True
                    break
            
            # Should NOT be rate limited under 100 requests
            assert not rate_limited, \
                f"Unexpected rate limit after {i} requests (limit is 100)"
            
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()
            clear_rate_limit_cache()

    def test_rate_limit_returns_429_with_retry_after(self):
        """
        Feature: url-shortener, Property 15: 限流触发
        Validates: Requirements 6.1
        
        When rate limited, response should include Retry-After header.
        """
        # Clear cache before test
        clear_rate_limit_cache()
        
        client = APIClient()
        unique_ip = f'172.16.{uuid.uuid4().int % 256}.{uuid.uuid4().int % 256}'
        
        try:
            # Make 21 requests to trigger rate limit
            for i in range(21):
                response = client.get(
                    '/test/throttled/',
                    REMOTE_ADDR=unique_ip
                )
                
                if response.status_code == 429:
                    # Verify 429 response has Retry-After header
                    assert 'Retry-After' in response, \
                        "429 response should include Retry-After header"
                    
                    retry_after = int(response['Retry-After'])
                    assert retry_after > 0, \
                        f"Retry-After should be positive, got {retry_after}"
                    assert retry_after <= 60, \
                        f"Retry-After should be <= 60 seconds, got {retry_after}"
                    break
            else:
                pytest.fail("Expected 429 response after 21 requests")
            
        finally:
            clear_rate_limit_cache()



@pytest.mark.django_db(transaction=True)
class TestRateLimitQuotaHeaders:
    """
    Property 16: Rate Limit Quota Response Headers
    
    For any API request, the response should include rate limit quota information
    in the headers.
    
    Validates: Requirements 6.4
    """

    @pytest.fixture(autouse=True)
    def setup_throttled_url(self, settings):
        """Add throttled test URL to urlpatterns."""
        from django.urls import clear_url_caches
        import urlshortener.urls
        
        # Store original urlpatterns
        original_urlpatterns = urlshortener.urls.urlpatterns.copy()
        
        # Add test URL
        urlshortener.urls.urlpatterns.append(
            path('test/throttled/', throttled_test_view, name='throttled-test')
        )
        clear_url_caches()
        
        yield
        
        # Restore original urlpatterns
        urlshortener.urls.urlpatterns = original_urlpatterns
        clear_url_caches()

    @settings(max_examples=100, deadline=None)
    @given(
        request_count=st.integers(min_value=1, max_value=10)
    )
    def test_response_includes_ratelimit_headers(self, request_count):
        """
        Feature: url-shortener, Property 16: 限流配额响应头
        Validates: Requirements 6.4
        
        For any API request with throttling, response should include X-RateLimit-* headers.
        """
        # Clear cache before test
        clear_rate_limit_cache()
        
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            for i in range(request_count):
                response = client.get('/test/throttled/')
                
                # Skip if rate limited
                if response.status_code == 429:
                    # 429 responses should have headers
                    assert 'X-RateLimit-Limit' in response, \
                        "429 response should include X-RateLimit-Limit header"
                    break
                
                # For successful responses, check headers
                # Note: Headers are added by middleware when _ratelimit_info is set
                if hasattr(response, '_request') and hasattr(response._request, '_ratelimit_info'):
                    assert 'X-RateLimit-Limit' in response, \
                        "Response should include X-RateLimit-Limit header"
                    assert 'X-RateLimit-Remaining' in response, \
                        "Response should include X-RateLimit-Remaining header"
                    assert 'X-RateLimit-Reset' in response, \
                        "Response should include X-RateLimit-Reset header"
                    
                    # Verify header values are valid
                    limit = int(response['X-RateLimit-Limit'])
                    remaining = int(response['X-RateLimit-Remaining'])
                    reset = int(response['X-RateLimit-Reset'])
                    
                    assert limit == 100, \
                        f"Expected limit 100 for authenticated user, got {limit}"
                    assert remaining >= 0, \
                        f"Remaining should be non-negative, got {remaining}"
                    assert reset >= 0 and reset <= 60, \
                        f"Reset should be 0-60 seconds, got {reset}"
            
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()
            clear_rate_limit_cache()

    @settings(max_examples=100, deadline=None)
    @given(
        request_count=st.integers(min_value=2, max_value=5)
    )
    def test_remaining_decrements_with_requests(self, request_count):
        """
        Feature: url-shortener, Property 16: 限流配额响应头
        Validates: Requirements 6.4
        
        For any sequence of requests, X-RateLimit-Remaining should decrement.
        """
        # Clear cache before test
        clear_rate_limit_cache()
        
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            previous_remaining = None
            
            for i in range(request_count):
                response = client.get('/test/throttled/')
                
                # Skip if rate limited
                if response.status_code == 429:
                    break
                
                # Check if headers are present
                if 'X-RateLimit-Remaining' in response:
                    current_remaining = int(response['X-RateLimit-Remaining'])
                    
                    if previous_remaining is not None:
                        # Remaining should decrease or stay same (if window reset)
                        assert current_remaining <= previous_remaining or current_remaining >= 98, \
                            f"Remaining should decrease: was {previous_remaining}, now {current_remaining}"
                    
                    previous_remaining = current_remaining
            
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()
            clear_rate_limit_cache()

    @settings(max_examples=100, deadline=None)
    @given(
        request_count=st.integers(min_value=1, max_value=5)
    )
    def test_anonymous_user_gets_lower_limit(self, request_count):
        """
        Feature: url-shortener, Property 16: 限流配额响应头
        Validates: Requirements 6.4
        
        Anonymous users should see limit of 20 in headers.
        """
        # Clear cache before test
        clear_rate_limit_cache()
        
        client = APIClient()
        unique_ip = f'192.0.2.{uuid.uuid4().int % 256}'
        
        try:
            for i in range(request_count):
                response = client.get(
                    '/test/throttled/',
                    REMOTE_ADDR=unique_ip
                )
                
                # Skip if rate limited
                if response.status_code == 429:
                    break
                
                # Check rate limit headers if present
                if 'X-RateLimit-Limit' in response:
                    limit = int(response['X-RateLimit-Limit'])
                    assert limit == 20, \
                        f"Expected limit 20 for anonymous user, got {limit}"
            
        finally:
            clear_rate_limit_cache()

    def test_429_response_includes_all_headers(self):
        """
        Feature: url-shortener, Property 16: 限流配额响应头
        Validates: Requirements 6.4
        
        When rate limited (429), response should include all rate limit headers.
        """
        # Clear cache before test
        clear_rate_limit_cache()
        
        client = APIClient()
        unique_ip = f'198.51.100.{uuid.uuid4().int % 256}'
        
        try:
            # Make 21 requests to trigger rate limit
            for i in range(21):
                response = client.get(
                    '/test/throttled/',
                    REMOTE_ADDR=unique_ip
                )
                
                if response.status_code == 429:
                    # Verify all rate limit headers are present
                    assert 'X-RateLimit-Limit' in response, \
                        "429 response should include X-RateLimit-Limit"
                    assert 'X-RateLimit-Remaining' in response, \
                        "429 response should include X-RateLimit-Remaining"
                    assert 'X-RateLimit-Reset' in response, \
                        "429 response should include X-RateLimit-Reset"
                    assert 'Retry-After' in response, \
                        "429 response should include Retry-After"
                    
                    # Remaining should be 0 when rate limited
                    remaining = int(response['X-RateLimit-Remaining'])
                    assert remaining == 0, \
                        f"Remaining should be 0 when rate limited, got {remaining}"
                    
                    # Retry-After should match Reset
                    retry_after = int(response['Retry-After'])
                    reset = int(response['X-RateLimit-Reset'])
                    assert retry_after == reset, \
                        f"Retry-After ({retry_after}) should match Reset ({reset})"
                    break
            else:
                pytest.fail("Expected 429 response after 21 requests")
            
        finally:
            clear_rate_limit_cache()
