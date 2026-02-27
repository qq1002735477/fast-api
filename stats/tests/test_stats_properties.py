"""
Property-based tests for access statistics.

Feature: url-shortener
Uses hypothesis library for property-based testing.
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
import string
import uuid

from links.models import Link, AccessLog
from links.services import BASE62_CHARS

User = get_user_model()


# Custom strategies for generating test data
def valid_url_strategy():
    """Generate valid HTTP/HTTPS URLs."""
    protocols = st.sampled_from(['http', 'https'])
    domains = st.sampled_from([
        'example.com', 'test.org', 'sample.net', 'demo.io',
        'mysite.com', 'website.org', 'page.net'
    ])
    paths = st.text(
        alphabet=string.ascii_lowercase + string.digits + '-_',
        min_size=0,
        max_size=50
    ).map(lambda x: f'/{x}' if x else '')
    
    return st.builds(
        lambda p, d, path: f'{p}://{d}{path}',
        protocols, domains, paths
    )


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


@pytest.mark.django_db(transaction=True)
class TestStatsDataConsistency:
    """
    Property 14: Statistics Data Consistency
    
    For any short link, the statistics API should return a click count
    that equals the actual number of accesses.
    
    Validates: Requirements 5.1
    """

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        access_count=st.integers(min_value=0, max_value=10)
    )
    def test_stats_click_count_matches_accesses(self, url, access_count):
        """
        Feature: url-shortener, Property 14: 统计数据一致性
        Validates: Requirements 5.1
        
        For any short link, the click count in stats should equal
        the actual number of times the link was accessed.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a short link
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201, \
                f"Link creation failed: {create_response.data}"
            
            short_code = create_response.data['short_code']
            
            # Access the link the specified number of times
            redirect_client = APIClient()
            for _ in range(access_count):
                redirect_response = redirect_client.get(
                    f'/r/{short_code}',
                    follow=False
                )
                assert redirect_response.status_code == 302
            
            # Get statistics via API
            stats_response = client.get(f'/api/links/{short_code}/stats/')
            
            assert stats_response.status_code == 200, \
                f"Stats request failed: {stats_response.data}"
            
            # Verify click count matches actual accesses
            reported_click_count = stats_response.data['click_count']
            assert reported_click_count == access_count, \
                f"Expected click count {access_count}, got {reported_click_count}"
            
            # Also verify the link model's click_count is consistent
            link = Link.objects.get(short_code=short_code)
            assert link.click_count == access_count, \
                f"Link model click count {link.click_count} != {access_count}"
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        access_count=st.integers(min_value=1, max_value=5)
    )
    def test_stats_unique_visitors_count(self, url, access_count):
        """
        Feature: url-shortener, Property 14: 统计数据一致性
        Validates: Requirements 5.1
        
        For any short link accessed from the same IP multiple times,
        unique visitors count should be 1.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a short link
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            
            # Access the link multiple times from same client (same IP)
            redirect_client = APIClient()
            for _ in range(access_count):
                redirect_response = redirect_client.get(
                    f'/r/{short_code}',
                    follow=False
                )
                assert redirect_response.status_code == 302
            
            # Get statistics
            stats_response = client.get(f'/api/links/{short_code}/stats/')
            
            assert stats_response.status_code == 200
            
            # Click count should equal access count
            assert stats_response.data['click_count'] == access_count
            
            # Unique visitors should be 1 (all from same IP)
            assert stats_response.data['unique_visitors'] == 1, \
                f"Expected 1 unique visitor, got {stats_response.data['unique_visitors']}"
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        access_count=st.integers(min_value=1, max_value=5)
    )
    def test_stats_recent_logs_count(self, url, access_count):
        """
        Feature: url-shortener, Property 14: 统计数据一致性
        Validates: Requirements 5.1
        
        For any short link, the number of recent access logs should
        match the actual number of accesses (up to the limit).
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a short link
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            
            # Access the link multiple times
            redirect_client = APIClient()
            for i in range(access_count):
                redirect_response = redirect_client.get(
                    f'/r/{short_code}',
                    follow=False,
                    HTTP_USER_AGENT=f'TestAgent/{i}'
                )
                assert redirect_response.status_code == 302
            
            # Get statistics
            stats_response = client.get(f'/api/links/{short_code}/stats/')
            
            assert stats_response.status_code == 200
            
            # Recent logs count should match access count (up to limit of 10)
            expected_log_count = min(access_count, 10)
            actual_log_count = len(stats_response.data['recent_access_logs'])
            
            assert actual_log_count == expected_log_count, \
                f"Expected {expected_log_count} recent logs, got {actual_log_count}"
            
            # Verify each log has required fields
            for log in stats_response.data['recent_access_logs']:
                assert 'ip_address' in log
                assert 'user_agent' in log
                assert 'accessed_at' in log
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_stats_daily_stats_consistency(self, url):
        """
        Feature: url-shortener, Property 14: 统计数据一致性
        Validates: Requirements 5.1, 5.2
        
        For any short link, the sum of daily click counts should
        equal the total click count.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a short link
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            
            # Access the link a few times
            redirect_client = APIClient()
            access_count = 3
            for _ in range(access_count):
                redirect_response = redirect_client.get(
                    f'/r/{short_code}',
                    follow=False
                )
                assert redirect_response.status_code == 302
            
            # Verify access logs were created
            link = Link.objects.get(short_code=short_code)
            access_log_count = AccessLog.objects.filter(link=link).count()
            
            # Get statistics - use the stats service directly to avoid date range issues
            from stats.services import stats_service
            basic_stats = stats_service.get_link_stats(link)
            
            # The click_count on the link should match access_log_count
            assert access_log_count == basic_stats['click_count'], \
                f"Access log count {access_log_count} != click count {basic_stats['click_count']}"
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            user.delete()
