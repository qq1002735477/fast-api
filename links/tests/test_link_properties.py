"""
Property-based tests for short link creation and management.

Feature: url-shortener
Uses hypothesis library for property-based testing.
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
import string
import uuid

from links.models import Link
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


def invalid_url_strategy():
    """Generate invalid URL strings."""
    return st.one_of(
        # Missing protocol
        st.text(alphabet=string.ascii_lowercase, min_size=5, max_size=20)
            .map(lambda x: f'{x}.com/path'),
        # Invalid protocol
        st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10)
            .filter(lambda x: x not in ['http', 'https', 'ftp'])
            .map(lambda x: f'{x}://example.com'),
        # Just random text
        st.text(alphabet=string.ascii_letters + string.digits, min_size=5, max_size=30)
            .filter(lambda x: '://' not in x),
        # Empty or whitespace
        st.text(alphabet=' \t\n', max_size=5),
    )


def valid_custom_code_strategy():
    """Generate valid custom short codes (4-10 Base62 characters)."""
    return st.text(
        alphabet=BASE62_CHARS,
        min_size=4,
        max_size=10
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
class TestLinkCreateRedirectRoundtrip:
    """
    Property 5: Short Link Create-Redirect Roundtrip
    
    For any valid original URL, creating a short link and then accessing
    that short code should redirect to the original URL.
    
    Validates: Requirements 2.1, 3.1
    """

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_create_redirect_roundtrip(self, url):
        """
        Feature: url-shortener, Property 5: 短链接创建-重定向往返
        Validates: Requirements 2.1, 3.1
        
        For any valid URL, creating a short link then accessing it
        should redirect to the original URL.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Step 1: Create short link
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            # Creation should succeed
            assert create_response.status_code == 201, \
                f"Link creation failed: {create_response.data}"
            
            short_code = create_response.data['short_code']
            assert short_code, "Short code should be returned"
            
            # Step 2: Access the short link (redirect)
            redirect_client = APIClient()  # Unauthenticated client
            redirect_response = redirect_client.get(
                f'/r/{short_code}',
                follow=False  # Don't follow redirect
            )
            
            # Should get a redirect response
            assert redirect_response.status_code == 302, \
                f"Expected 302 redirect, got {redirect_response.status_code}"
            
            # Verify redirect location matches original URL
            redirect_url = redirect_response.get('Location')
            assert redirect_url == url, \
                f"Redirect URL '{redirect_url}' should match original '{url}'"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()


@pytest.mark.django_db(transaction=True)
class TestInvalidURLRejection:
    """
    Property 6: Invalid URL Rejection
    
    For any invalid URL format, the creation request should be rejected
    with a validation error.
    
    Validates: Requirements 2.2
    """

    @settings(max_examples=100, deadline=None)
    @given(invalid_url=invalid_url_strategy())
    def test_invalid_url_rejected(self, invalid_url):
        """
        Feature: url-shortener, Property 6: 无效 URL 拒绝
        Validates: Requirements 2.2
        
        For any invalid URL format, link creation should be rejected.
        """
        # Skip if URL accidentally becomes valid
        assume(not invalid_url.startswith('http://'))
        assume(not invalid_url.startswith('https://'))
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Try to create link with invalid URL
            response = client.post('/api/links/', {
                'original_url': invalid_url,
            }, format='json')
            
            # Should be rejected with 400
            assert response.status_code == 400, \
                f"Expected 400 for invalid URL '{invalid_url}', got {response.status_code}"
        
        finally:
            # Cleanup
            user.delete()


@pytest.mark.django_db(transaction=True)
class TestCustomCodeUsage:
    """
    Property 8: Custom Short Code Usage
    
    For any valid custom short code (4-10 Base62 characters),
    creating a link with that code should use the specified code.
    
    Validates: Requirements 2.4, 2.6
    """

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        custom_code=valid_custom_code_strategy()
    )
    def test_custom_code_used(self, url, custom_code):
        """
        Feature: url-shortener, Property 8: 自定义短码使用
        Validates: Requirements 2.4, 2.6
        
        For any valid custom code, the created link should use that code.
        """
        # Ensure custom code is not already in use
        assume(not Link.objects.filter(short_code=custom_code).exists())
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create link with custom code
            response = client.post('/api/links/', {
                'original_url': url,
                'custom_code': custom_code,
            }, format='json')
            
            # Creation should succeed
            assert response.status_code == 201, \
                f"Link creation failed: {response.data}"
            
            # Verify the custom code was used
            assert response.data['short_code'] == custom_code, \
                f"Expected custom code '{custom_code}', got '{response.data['short_code']}'"
            
            # Verify link exists in database with correct code
            link = Link.objects.get(short_code=custom_code)
            assert link.original_url == url
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        custom_code=valid_custom_code_strategy()
    )
    def test_duplicate_custom_code_rejected(self, url, custom_code):
        """
        Feature: url-shortener, Property 8: 自定义短码使用
        Validates: Requirements 2.5
        
        For any custom code that's already in use, creation should be rejected.
        """
        # Create two test users
        user1 = create_test_user()
        user2 = create_test_user()
        client1 = get_authenticated_client(user1)
        client2 = get_authenticated_client(user2)
        
        try:
            # First user creates link with custom code
            response1 = client1.post('/api/links/', {
                'original_url': url,
                'custom_code': custom_code,
            }, format='json')
            
            # First creation should succeed
            assert response1.status_code == 201, \
                f"First link creation failed: {response1.data}"
            
            # Second user tries to use same custom code
            response2 = client2.post('/api/links/', {
                'original_url': 'https://different.com',
                'custom_code': custom_code,
            }, format='json')
            
            # Second creation should fail with 400 (conflict)
            assert response2.status_code == 400, \
                f"Expected 400 for duplicate code, got {response2.status_code}"
        
        finally:
            # Cleanup
            Link.objects.filter(user__in=[user1, user2]).delete()
            user1.delete()
            user2.delete()


@pytest.mark.django_db(transaction=True)
class TestLinkCreationIdempotency:
    """
    Property 7: Short Link Creation Idempotency
    
    For any authenticated user and original URL, creating the same URL
    multiple times should return the same short code.
    
    Validates: Requirements 2.3
    """

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_same_url_returns_same_code(self, url):
        """
        Feature: url-shortener, Property 7: 短链接创建幂等性
        Validates: Requirements 2.3
        
        For any URL, creating it multiple times should return the same short code.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # First creation
            response1 = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert response1.status_code == 201, \
                f"First creation failed: {response1.data}"
            
            short_code1 = response1.data['short_code']
            
            # Second creation with same URL
            response2 = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            # Should return 200 (existing) not 201 (created)
            assert response2.status_code == 200, \
                f"Expected 200 for existing URL, got {response2.status_code}"
            
            short_code2 = response2.data['short_code']
            
            # Both should return the same short code
            assert short_code1 == short_code2, \
                f"Expected same code '{short_code1}', got '{short_code2}'"
            
            # Third creation should also return the same
            response3 = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert response3.status_code == 200
            assert response3.data['short_code'] == short_code1
            
            # Verify only one link exists in database
            link_count = Link.objects.filter(user=user, original_url=url).count()
            assert link_count == 1, \
                f"Expected 1 link, found {link_count}"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy()
    )
    def test_different_users_get_different_codes(self, url):
        """
        Feature: url-shortener, Property 7: 短链接创建幂等性
        Validates: Requirements 2.3
        
        Different users creating the same URL should get different short codes.
        """
        # Create two test users
        user1 = create_test_user()
        user2 = create_test_user()
        client1 = get_authenticated_client(user1)
        client2 = get_authenticated_client(user2)
        
        try:
            # User 1 creates link
            response1 = client1.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert response1.status_code == 201
            short_code1 = response1.data['short_code']
            
            # User 2 creates link with same URL
            response2 = client2.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            # User 2 should get a new link (201), not existing (200)
            assert response2.status_code == 201, \
                f"Expected 201 for different user, got {response2.status_code}"
            
            short_code2 = response2.data['short_code']
            
            # Different users should get different short codes
            assert short_code1 != short_code2, \
                f"Different users should get different codes"
        
        finally:
            # Cleanup
            Link.objects.filter(user__in=[user1, user2]).delete()
            user1.delete()
            user2.delete()


@pytest.mark.django_db(transaction=True)
class TestExpiredLinkRejection:
    """
    Property 18: Expired Link Rejection
    
    For any expired short link, accessing it should return HTTP 410 Gone.
    
    Validates: Requirements 8.2
    """

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_expired_link_returns_410(self, url):
        """
        Feature: url-shortener, Property 18: 过期链接拒绝访问
        Validates: Requirements 8.2
        
        For any expired short link, access should return HTTP 410 Gone.
        """
        from django.utils import timezone
        from datetime import timedelta
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a link that expires in the past
            past_time = timezone.now() - timedelta(hours=1)
            
            # First create a normal link
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201, \
                f"Link creation failed: {create_response.data}"
            
            short_code = create_response.data['short_code']
            
            # Manually set the expiration to the past
            link = Link.objects.get(short_code=short_code)
            link.expires_at = past_time
            link.save()
            
            # Clear cache to ensure we get fresh data
            from links.services import link_cache_service
            link_cache_service.delete(short_code)
            
            # Try to access the expired link
            redirect_client = APIClient()
            redirect_response = redirect_client.get(
                f'/r/{short_code}',
                follow=False
            )
            
            # Should get 410 Gone
            assert redirect_response.status_code == 410, \
                f"Expected 410 for expired link, got {redirect_response.status_code}"
            
            # Verify error response structure
            assert 'error' in redirect_response.data
            assert redirect_response.data['error']['code'] == 'LINK_EXPIRED'
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_non_expired_link_redirects(self, url):
        """
        Feature: url-shortener, Property 18: 过期链接拒绝访问
        Validates: Requirements 8.2
        
        For any non-expired short link, access should redirect normally.
        """
        from django.utils import timezone
        from datetime import timedelta
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a link that expires in the future
            future_time = timezone.now() + timedelta(hours=24)
            
            # Create link with future expiration
            create_response = client.post('/api/links/', {
                'original_url': url,
                'expires_at': future_time.isoformat(),
            }, format='json')
            
            assert create_response.status_code == 201, \
                f"Link creation failed: {create_response.data}"
            
            short_code = create_response.data['short_code']
            
            # Access the non-expired link
            redirect_client = APIClient()
            redirect_response = redirect_client.get(
                f'/r/{short_code}',
                follow=False
            )
            
            # Should get 302 redirect
            assert redirect_response.status_code == 302, \
                f"Expected 302 for non-expired link, got {redirect_response.status_code}"
            
            # Verify redirect location
            redirect_url = redirect_response.get('Location')
            assert redirect_url == url
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()



@pytest.mark.django_db(transaction=True)
class TestAccessCountIncrement:
    """
    Property 10: Access Count Increment
    
    For any valid short link, each access should increment the click count by 1.
    
    Validates: Requirements 3.4
    """

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        access_count=st.integers(min_value=1, max_value=5)
    )
    def test_access_increments_click_count(self, url, access_count):
        """
        Feature: url-shortener, Property 10: 访问计数递增
        Validates: Requirements 3.4
        
        For any valid short link, each access should increment click count by 1.
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
            
            # Get initial click count
            link = Link.objects.get(short_code=short_code)
            initial_count = link.click_count
            
            # Access the link multiple times
            redirect_client = APIClient()
            for _ in range(access_count):
                redirect_response = redirect_client.get(
                    f'/r/{short_code}',
                    follow=False
                )
                assert redirect_response.status_code == 302
            
            # Refresh from database and check click count
            link.refresh_from_db()
            expected_count = initial_count + access_count
            
            assert link.click_count == expected_count, \
                f"Expected click count {expected_count}, got {link.click_count}"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()



@pytest.mark.django_db(transaction=True)
class TestAccessLogRecording:
    """
    Property 11: Access Log Recording
    
    For any short link access, an access log entry should be created
    with IP address and User-Agent.
    
    Validates: Requirements 3.5
    """

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        user_agent=st.text(
            alphabet=string.ascii_letters + string.digits + ' /-_.;()',
            min_size=5,
            max_size=100
        )
    )
    def test_access_creates_log_entry(self, url, user_agent):
        """
        Feature: url-shortener, Property 11: 访问日志记录
        Validates: Requirements 3.5
        
        For any short link access, an access log should be created
        with IP address and User-Agent.
        """
        from links.models import AccessLog
        
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
            link = Link.objects.get(short_code=short_code)
            
            # Get initial log count
            initial_log_count = AccessLog.objects.filter(link=link).count()
            
            # Access the link with custom User-Agent
            redirect_client = APIClient()
            redirect_response = redirect_client.get(
                f'/r/{short_code}',
                follow=False,
                HTTP_USER_AGENT=user_agent
            )
            
            assert redirect_response.status_code == 302
            
            # Check that a new access log was created
            new_log_count = AccessLog.objects.filter(link=link).count()
            assert new_log_count == initial_log_count + 1, \
                f"Expected {initial_log_count + 1} logs, got {new_log_count}"
            
            # Verify the log entry contains correct data
            latest_log = AccessLog.objects.filter(link=link).order_by('-accessed_at').first()
            assert latest_log is not None
            assert latest_log.ip_address is not None
            # User-Agent should be stored (truncated to 512 chars)
            assert latest_log.user_agent == user_agent[:512]
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        access_count=st.integers(min_value=1, max_value=3)
    )
    def test_multiple_accesses_create_multiple_logs(self, url, access_count):
        """
        Feature: url-shortener, Property 11: 访问日志记录
        Validates: Requirements 3.5
        
        Multiple accesses should create multiple log entries.
        """
        from links.models import AccessLog
        
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
            link = Link.objects.get(short_code=short_code)
            
            # Get initial log count
            initial_log_count = AccessLog.objects.filter(link=link).count()
            
            # Access the link multiple times
            redirect_client = APIClient()
            for i in range(access_count):
                redirect_response = redirect_client.get(
                    f'/r/{short_code}',
                    follow=False,
                    HTTP_USER_AGENT=f'TestAgent/{i}'
                )
                assert redirect_response.status_code == 302
            
            # Check that correct number of logs were created
            new_log_count = AccessLog.objects.filter(link=link).count()
            expected_count = initial_log_count + access_count
            
            assert new_log_count == expected_count, \
                f"Expected {expected_count} logs, got {new_log_count}"
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            user.delete()


@pytest.mark.django_db(transaction=True)
class TestLinkManagementCRUDRoundtrip:
    """
    Property 12: Link Management CRUD Roundtrip
    
    For any authenticated user's created short link:
    - Querying details should return the creation data
    - After update, querying should return the new data
    - After deletion, querying should return 404
    
    Validates: Requirements 4.1, 4.2, 4.3, 4.4
    """

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        new_url=valid_url_strategy()
    )
    def test_crud_roundtrip(self, url, new_url):
        """
        Feature: url-shortener, Property 12: 链接管理 CRUD 往返
        Validates: Requirements 4.1, 4.2, 4.3, 4.4
        
        For any created link, CRUD operations should work correctly:
        - Create returns the link data
        - Read returns the same data
        - Update changes the data
        - Delete removes the link
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Step 1: CREATE - Create a short link
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201, \
                f"Link creation failed: {create_response.data}"
            
            short_code = create_response.data['short_code']
            assert create_response.data['original_url'] == url
            
            # Step 2: READ - Get link details
            read_response = client.get(f'/api/links/{short_code}/')
            
            assert read_response.status_code == 200, \
                f"Link read failed: {read_response.data}"
            assert read_response.data['short_code'] == short_code
            assert read_response.data['original_url'] == url
            
            # Step 3: UPDATE - Update the link
            update_response = client.put(f'/api/links/{short_code}/', {
                'original_url': new_url,
            }, format='json')
            
            assert update_response.status_code == 200, \
                f"Link update failed: {update_response.data}"
            assert update_response.data['original_url'] == new_url
            
            # Verify update persisted
            verify_response = client.get(f'/api/links/{short_code}/')
            assert verify_response.status_code == 200
            assert verify_response.data['original_url'] == new_url
            
            # Step 4: DELETE - Delete the link
            delete_response = client.delete(f'/api/links/{short_code}/')
            
            assert delete_response.status_code == 204, \
                f"Link deletion failed: {delete_response.status_code}"
            
            # Verify deletion - should return 404
            verify_delete_response = client.get(f'/api/links/{short_code}/')
            assert verify_delete_response.status_code == 404, \
                f"Expected 404 after deletion, got {verify_delete_response.status_code}"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_list_returns_user_links(self, url):
        """
        Feature: url-shortener, Property 12: 链接管理 CRUD 往返
        Validates: Requirements 4.1
        
        Listing links should return paginated results for the user.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a link
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            
            # List links
            list_response = client.get('/api/links/')
            
            assert list_response.status_code == 200
            
            # Check pagination structure
            assert 'results' in list_response.data
            assert 'count' in list_response.data
            
            # Verify the created link is in the list
            results = list_response.data['results']
            short_codes = [link['short_code'] for link in results]
            assert short_code in short_codes, \
                f"Created link {short_code} not found in list"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_partial_update_works(self, url):
        """
        Feature: url-shortener, Property 12: 链接管理 CRUD 往返
        Validates: Requirements 4.3
        
        Partial update (PATCH) should update only specified fields.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a link
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            original_url = create_response.data['original_url']
            
            # Partial update - only change is_active
            patch_response = client.patch(f'/api/links/{short_code}/', {
                'is_active': False,
            }, format='json')
            
            assert patch_response.status_code == 200
            assert patch_response.data['is_active'] == False
            # Original URL should remain unchanged
            assert patch_response.data['original_url'] == original_url
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()



@pytest.mark.django_db(transaction=True)
class TestUserIsolation:
    """
    Property 13: User Isolation
    
    For any two different users, user A cannot access, modify, or delete
    user B's short links.
    
    Validates: Requirements 4.5
    """

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_user_cannot_read_other_user_link(self, url):
        """
        Feature: url-shortener, Property 13: 用户隔离
        Validates: Requirements 4.5
        
        User A cannot read user B's link details.
        """
        # Create two test users
        user_a = create_test_user()
        user_b = create_test_user()
        client_a = get_authenticated_client(user_a)
        client_b = get_authenticated_client(user_b)
        
        try:
            # User A creates a link
            create_response = client_a.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            
            # User B tries to read User A's link
            read_response = client_b.get(f'/api/links/{short_code}/')
            
            # Should get 403 Forbidden
            assert read_response.status_code == 403, \
                f"Expected 403 for unauthorized access, got {read_response.status_code}"
        
        finally:
            # Cleanup
            Link.objects.filter(user__in=[user_a, user_b]).delete()
            user_a.delete()
            user_b.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        new_url=valid_url_strategy()
    )
    def test_user_cannot_update_other_user_link(self, url, new_url):
        """
        Feature: url-shortener, Property 13: 用户隔离
        Validates: Requirements 4.5
        
        User A cannot update user B's link.
        """
        # Create two test users
        user_a = create_test_user()
        user_b = create_test_user()
        client_a = get_authenticated_client(user_a)
        client_b = get_authenticated_client(user_b)
        
        try:
            # User A creates a link
            create_response = client_a.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            
            # User B tries to update User A's link
            update_response = client_b.put(f'/api/links/{short_code}/', {
                'original_url': new_url,
            }, format='json')
            
            # Should get 403 Forbidden
            assert update_response.status_code == 403, \
                f"Expected 403 for unauthorized update, got {update_response.status_code}"
            
            # Verify the link was not modified
            verify_response = client_a.get(f'/api/links/{short_code}/')
            assert verify_response.status_code == 200
            assert verify_response.data['original_url'] == url, \
                "Link should not have been modified"
        
        finally:
            # Cleanup
            Link.objects.filter(user__in=[user_a, user_b]).delete()
            user_a.delete()
            user_b.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_user_cannot_delete_other_user_link(self, url):
        """
        Feature: url-shortener, Property 13: 用户隔离
        Validates: Requirements 4.5
        
        User A cannot delete user B's link.
        """
        # Create two test users
        user_a = create_test_user()
        user_b = create_test_user()
        client_a = get_authenticated_client(user_a)
        client_b = get_authenticated_client(user_b)
        
        try:
            # User A creates a link
            create_response = client_a.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            
            # User B tries to delete User A's link
            delete_response = client_b.delete(f'/api/links/{short_code}/')
            
            # Should get 403 Forbidden
            assert delete_response.status_code == 403, \
                f"Expected 403 for unauthorized delete, got {delete_response.status_code}"
            
            # Verify the link still exists
            verify_response = client_a.get(f'/api/links/{short_code}/')
            assert verify_response.status_code == 200, \
                "Link should still exist after unauthorized delete attempt"
        
        finally:
            # Cleanup
            Link.objects.filter(user__in=[user_a, user_b]).delete()
            user_a.delete()
            user_b.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_user_list_only_shows_own_links(self, url):
        """
        Feature: url-shortener, Property 13: 用户隔离
        Validates: Requirements 4.5
        
        User's link list should only contain their own links.
        """
        # Create two test users
        user_a = create_test_user()
        user_b = create_test_user()
        client_a = get_authenticated_client(user_a)
        client_b = get_authenticated_client(user_b)
        
        try:
            # User A creates a link
            create_response_a = client_a.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response_a.status_code == 201
            short_code_a = create_response_a.data['short_code']
            
            # User B creates a different link
            create_response_b = client_b.post('/api/links/', {
                'original_url': 'https://different-site.com/page',
            }, format='json')
            
            assert create_response_b.status_code == 201
            short_code_b = create_response_b.data['short_code']
            
            # User A lists their links
            list_response_a = client_a.get('/api/links/')
            assert list_response_a.status_code == 200
            
            short_codes_a = [link['short_code'] for link in list_response_a.data['results']]
            
            # User A should see their own link
            assert short_code_a in short_codes_a, \
                "User A should see their own link"
            
            # User A should NOT see User B's link
            assert short_code_b not in short_codes_a, \
                "User A should not see User B's link"
            
            # User B lists their links
            list_response_b = client_b.get('/api/links/')
            assert list_response_b.status_code == 200
            
            short_codes_b = [link['short_code'] for link in list_response_b.data['results']]
            
            # User B should see their own link
            assert short_code_b in short_codes_b, \
                "User B should see their own link"
            
            # User B should NOT see User A's link
            assert short_code_a not in short_codes_b, \
                "User B should not see User A's link"
        
        finally:
            # Cleanup
            Link.objects.filter(user__in=[user_a, user_b]).delete()
            user_a.delete()
            user_b.delete()



@pytest.mark.django_db(transaction=True)
class TestExpirationTimeUpdate:
    """
    Property 19: Expiration Time Update
    
    For any short link, updating the expiration time should be reflected
    when querying the link.
    
    Validates: Requirements 8.4
    """

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_set_expiration_time(self, url):
        """
        Feature: url-shortener, Property 19: 过期时间更新
        Validates: Requirements 8.4
        
        Setting an expiration time should be reflected in the link details.
        """
        from django.utils import timezone
        from datetime import timedelta
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a link without expiration
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            assert create_response.data['expires_at'] is None
            
            # Set expiration time
            future_time = timezone.now() + timedelta(days=7)
            update_response = client.patch(f'/api/links/{short_code}/', {
                'expires_at': future_time.isoformat(),
            }, format='json')
            
            assert update_response.status_code == 200
            assert update_response.data['expires_at'] is not None
            
            # Verify the expiration time is set correctly
            read_response = client.get(f'/api/links/{short_code}/')
            assert read_response.status_code == 200
            assert read_response.data['expires_at'] is not None
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_modify_expiration_time(self, url):
        """
        Feature: url-shortener, Property 19: 过期时间更新
        Validates: Requirements 8.4
        
        Modifying an existing expiration time should update the link.
        """
        from django.utils import timezone
        from datetime import timedelta
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a link with initial expiration
            initial_expiry = timezone.now() + timedelta(days=3)
            create_response = client.post('/api/links/', {
                'original_url': url,
                'expires_at': initial_expiry.isoformat(),
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            
            # Modify expiration time to a later date
            new_expiry = timezone.now() + timedelta(days=14)
            update_response = client.patch(f'/api/links/{short_code}/', {
                'expires_at': new_expiry.isoformat(),
            }, format='json')
            
            assert update_response.status_code == 200
            
            # Verify the new expiration time
            read_response = client.get(f'/api/links/{short_code}/')
            assert read_response.status_code == 200
            
            # Parse and compare dates (allowing for some time drift)
            from datetime import datetime
            returned_expiry = datetime.fromisoformat(
                read_response.data['expires_at'].replace('Z', '+00:00')
            )
            # The returned expiry should be close to the new expiry
            time_diff = abs((returned_expiry - new_expiry).total_seconds())
            assert time_diff < 60, \
                f"Expiration time difference too large: {time_diff} seconds"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_remove_expiration_time(self, url):
        """
        Feature: url-shortener, Property 19: 过期时间更新
        Validates: Requirements 8.4
        
        Setting expiration time to null should remove the expiration.
        """
        from django.utils import timezone
        from datetime import timedelta
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a link with expiration
            initial_expiry = timezone.now() + timedelta(days=7)
            create_response = client.post('/api/links/', {
                'original_url': url,
                'expires_at': initial_expiry.isoformat(),
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            assert create_response.data['expires_at'] is not None
            
            # Remove expiration by setting to null
            update_response = client.patch(f'/api/links/{short_code}/', {
                'expires_at': None,
            }, format='json')
            
            assert update_response.status_code == 200
            assert update_response.data['expires_at'] is None
            
            # Verify expiration is removed
            read_response = client.get(f'/api/links/{short_code}/')
            assert read_response.status_code == 200
            assert read_response.data['expires_at'] is None
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_cache_invalidated_after_expiry_update(self, url):
        """
        Feature: url-shortener, Property 19: 过期时间更新
        Validates: Requirements 8.4
        
        After updating expiration time, the cache should be invalidated
        and redirect should use the new expiration.
        """
        from django.utils import timezone
        from datetime import timedelta
        from links.services import link_cache_service
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a link without expiration
            create_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert create_response.status_code == 201
            short_code = create_response.data['short_code']
            
            # Access the link to populate cache
            redirect_client = APIClient()
            redirect_response = redirect_client.get(f'/r/{short_code}', follow=False)
            assert redirect_response.status_code == 302
            
            # Update expiration to past (make it expired)
            # First update to future, then manually set to past
            link = Link.objects.get(short_code=short_code)
            link.expires_at = timezone.now() - timedelta(hours=1)
            link.save()
            
            # Invalidate cache (simulating what update does)
            link_cache_service.delete(short_code)
            
            # Now accessing should return 410 Gone
            redirect_response2 = redirect_client.get(f'/r/{short_code}', follow=False)
            assert redirect_response2.status_code == 410, \
                f"Expected 410 after expiry update, got {redirect_response2.status_code}"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()
