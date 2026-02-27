"""
Property-based tests for batch link operations.

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
class TestBatchCreateIntegrity:
    """
    Property 20: Batch Create Integrity
    
    For any valid URL list (up to 50), batch creation should create
    a short link for each URL, and the number of results should equal
    the number of inputs.
    
    Validates: Requirements 9.1
    """

    @settings(max_examples=100, deadline=None)
    @given(
        urls=st.lists(
            valid_url_strategy(),
            min_size=1,
            max_size=10,
            unique=True
        )
    )
    def test_batch_create_returns_result_for_each_url(self, urls):
        """
        Feature: url-shortener, Property 20: 批量创建完整性
        Validates: Requirements 9.1
        
        For any list of valid URLs, batch creation should return
        a result for each URL with the count matching input count.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Prepare batch request
            links_data = [{'original_url': url} for url in urls]
            
            # Make batch create request
            response = client.post('/api/links/batch/', {
                'links': links_data
            }, format='json')
            
            # Should succeed (201 or 202 for async)
            assert response.status_code in [201, 202], \
                f"Batch creation failed: {response.data}"
            
            # Check response structure
            assert 'total' in response.data
            assert 'successful' in response.data
            assert 'failed' in response.data
            assert 'results' in response.data
            
            # Total should match input count
            assert response.data['total'] == len(urls), \
                f"Expected total {len(urls)}, got {response.data['total']}"
            
            # Results count should match input count
            assert len(response.data['results']) == len(urls), \
                f"Expected {len(urls)} results, got {len(response.data['results'])}"
            
            # All should be successful for valid URLs
            assert response.data['successful'] == len(urls), \
                f"Expected {len(urls)} successful, got {response.data['successful']}"
            
            assert response.data['failed'] == 0, \
                f"Expected 0 failed, got {response.data['failed']}"
            
            # Each result should have a short_code
            for result in response.data['results']:
                assert result['success'] is True
                assert result['short_code'] is not None
                assert result['error'] is None
            
            # Verify links exist in database
            for result in response.data['results']:
                link = Link.objects.filter(short_code=result['short_code']).first()
                assert link is not None, \
                    f"Link with short_code {result['short_code']} not found in database"
                assert link.user == user
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        urls=st.lists(
            valid_url_strategy(),
            min_size=1,
            max_size=5,
            unique=True
        )
    )
    def test_batch_create_all_links_accessible(self, urls):
        """
        Feature: url-shortener, Property 20: 批量创建完整性
        Validates: Requirements 9.1
        
        All links created in batch should be accessible via redirect.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Prepare batch request
            links_data = [{'original_url': url} for url in urls]
            
            # Make batch create request
            response = client.post('/api/links/batch/', {
                'links': links_data
            }, format='json')
            
            assert response.status_code in [201, 202]
            
            # Verify each created link redirects correctly
            redirect_client = APIClient()
            for i, result in enumerate(response.data['results']):
                if result['success']:
                    redirect_response = redirect_client.get(
                        f"/r/{result['short_code']}",
                        follow=False
                    )
                    assert redirect_response.status_code == 302, \
                        f"Expected 302 for {result['short_code']}, got {redirect_response.status_code}"
                    
                    redirect_url = redirect_response.get('Location')
                    assert redirect_url == urls[i], \
                        f"Redirect URL mismatch for index {i}"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()


@pytest.mark.django_db(transaction=True)
class TestBatchCreatePartialSuccess:
    """
    Property 21: Batch Create Partial Success
    
    For any list containing both valid and invalid URLs, batch creation
    should successfully create links for valid URLs and return errors
    for invalid URLs.
    
    Validates: Requirements 9.2
    """

    @settings(max_examples=100, deadline=None)
    @given(
        valid_urls=st.lists(
            valid_url_strategy(),
            min_size=1,
            max_size=5,
            unique=True
        ),
        invalid_urls=st.lists(
            invalid_url_strategy(),
            min_size=1,
            max_size=5
        )
    )
    def test_batch_create_partial_success(self, valid_urls, invalid_urls):
        """
        Feature: url-shortener, Property 21: 批量创建部分成功
        Validates: Requirements 9.2
        
        For any mix of valid and invalid URLs, valid ones should succeed
        and invalid ones should fail with appropriate errors.
        """
        # Filter out any accidentally valid URLs from invalid list
        filtered_invalid = [
            url for url in invalid_urls 
            if not url.startswith('http://') and not url.startswith('https://')
        ]
        
        # Skip if no invalid URLs remain after filtering
        assume(len(filtered_invalid) > 0)
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Prepare mixed batch request - interleave valid and invalid
            links_data = []
            valid_indices = []
            invalid_indices = []
            
            # Add valid URLs
            for i, url in enumerate(valid_urls):
                links_data.append({'original_url': url})
                valid_indices.append(len(links_data) - 1)
            
            # Add invalid URLs
            for url in filtered_invalid:
                links_data.append({'original_url': url})
                invalid_indices.append(len(links_data) - 1)
            
            # Make batch create request
            response = client.post('/api/links/batch/', {
                'links': links_data
            }, format='json')
            
            # Should return 201 (partial success) or 400 (all failed)
            assert response.status_code in [201, 400], \
                f"Unexpected status code: {response.status_code}"
            
            # Check response structure
            assert 'total' in response.data
            assert 'successful' in response.data
            assert 'failed' in response.data
            assert 'results' in response.data
            
            # Total should match input count
            assert response.data['total'] == len(links_data), \
                f"Expected total {len(links_data)}, got {response.data['total']}"
            
            # Results count should match input count
            assert len(response.data['results']) == len(links_data), \
                f"Expected {len(links_data)} results, got {len(response.data['results'])}"
            
            # Valid URLs should succeed
            assert response.data['successful'] >= len(valid_urls), \
                f"Expected at least {len(valid_urls)} successful, got {response.data['successful']}"
            
            # Invalid URLs should fail
            assert response.data['failed'] >= len(filtered_invalid), \
                f"Expected at least {len(filtered_invalid)} failed, got {response.data['failed']}"
            
            # Check individual results
            for idx in valid_indices:
                result = response.data['results'][idx]
                assert result['success'] is True, \
                    f"Valid URL at index {idx} should succeed"
                assert result['short_code'] is not None
            
            for idx in invalid_indices:
                result = response.data['results'][idx]
                assert result['success'] is False, \
                    f"Invalid URL at index {idx} should fail"
                assert result['error'] is not None
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        valid_urls=st.lists(
            valid_url_strategy(),
            min_size=2,
            max_size=5,
            unique=True
        )
    )
    def test_batch_create_duplicate_custom_code_partial_success(self, valid_urls):
        """
        Feature: url-shortener, Property 21: 批量创建部分成功
        Validates: Requirements 9.2
        
        When batch contains duplicate custom codes, first should succeed
        and subsequent ones should fail.
        """
        assume(len(valid_urls) >= 2)
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Use same custom code for first two URLs
            custom_code = 'test' + str(uuid.uuid4())[:4]
            
            links_data = [
                {'original_url': valid_urls[0], 'custom_code': custom_code},
                {'original_url': valid_urls[1], 'custom_code': custom_code},
            ]
            
            # Add remaining URLs without custom codes
            for url in valid_urls[2:]:
                links_data.append({'original_url': url})
            
            # Make batch create request
            response = client.post('/api/links/batch/', {
                'links': links_data
            }, format='json')
            
            # Should return 201 (partial success)
            assert response.status_code == 201, \
                f"Expected 201, got {response.status_code}: {response.data}"
            
            # First with custom code should succeed
            assert response.data['results'][0]['success'] is True
            assert response.data['results'][0]['short_code'] == custom_code
            
            # Second with same custom code should fail
            assert response.data['results'][1]['success'] is False
            assert 'already in use' in response.data['results'][1]['error'].lower() or \
                   'custom code' in response.data['results'][1]['error'].lower()
            
            # Successful count should be total - 1 (one duplicate failure)
            assert response.data['successful'] == len(links_data) - 1
            assert response.data['failed'] == 1
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()


@pytest.mark.django_db(transaction=True)
class TestBatchDeleteIntegrity:
    """
    Property 22: Batch Delete Integrity
    
    For any list of short codes, batch deletion should delete all
    specified links owned by the user, and all deleted links should
    become inaccessible.
    
    Validates: Requirements 9.3
    """

    @settings(max_examples=100, deadline=None)
    @given(
        urls=st.lists(
            valid_url_strategy(),
            min_size=1,
            max_size=5,
            unique=True
        )
    )
    def test_batch_delete_removes_all_links(self, urls):
        """
        Feature: url-shortener, Property 22: 批量删除完整性
        Validates: Requirements 9.3
        
        For any list of short codes, batch deletion should remove
        all specified links and make them inaccessible.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # First, create links via batch
            links_data = [{'original_url': url} for url in urls]
            create_response = client.post('/api/links/batch/', {
                'links': links_data
            }, format='json')
            
            assert create_response.status_code == 201
            
            # Collect short codes
            short_codes = [
                result['short_code'] 
                for result in create_response.data['results']
                if result['success']
            ]
            
            assert len(short_codes) == len(urls)
            
            # Verify links exist before deletion
            for short_code in short_codes:
                assert Link.objects.filter(short_code=short_code).exists()
            
            # Batch delete
            delete_response = client.post('/api/links/batch/delete/', {
                'short_codes': short_codes
            }, format='json')
            
            assert delete_response.status_code == 200
            
            # Check response structure
            assert 'total' in delete_response.data
            assert 'successful' in delete_response.data
            assert 'failed' in delete_response.data
            assert 'results' in delete_response.data
            
            # All should be successfully deleted
            assert delete_response.data['total'] == len(short_codes)
            assert delete_response.data['successful'] == len(short_codes)
            assert delete_response.data['failed'] == 0
            
            # Verify all links are deleted from database
            for short_code in short_codes:
                assert not Link.objects.filter(short_code=short_code).exists(), \
                    f"Link {short_code} should be deleted"
            
            # Verify links are inaccessible via redirect
            redirect_client = APIClient()
            for short_code in short_codes:
                redirect_response = redirect_client.get(
                    f'/r/{short_code}',
                    follow=False
                )
                assert redirect_response.status_code == 404, \
                    f"Deleted link {short_code} should return 404"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        urls=st.lists(
            valid_url_strategy(),
            min_size=2,
            max_size=5,
            unique=True
        )
    )
    def test_batch_delete_only_deletes_owned_links(self, urls):
        """
        Feature: url-shortener, Property 22: 批量删除完整性
        Validates: Requirements 9.3
        
        Batch delete should only delete links owned by the requesting user.
        """
        assume(len(urls) >= 2)
        
        # Create two test users
        user1 = create_test_user()
        user2 = create_test_user()
        client1 = get_authenticated_client(user1)
        client2 = get_authenticated_client(user2)
        
        try:
            # User 1 creates links
            links_data = [{'original_url': url} for url in urls]
            create_response = client1.post('/api/links/batch/', {
                'links': links_data
            }, format='json')
            
            assert create_response.status_code == 201
            
            short_codes = [
                result['short_code'] 
                for result in create_response.data['results']
                if result['success']
            ]
            
            # User 2 tries to delete User 1's links
            delete_response = client2.post('/api/links/batch/delete/', {
                'short_codes': short_codes
            }, format='json')
            
            assert delete_response.status_code == 200
            
            # All should fail (not owned by user2)
            assert delete_response.data['successful'] == 0
            assert delete_response.data['failed'] == len(short_codes)
            
            # Verify links still exist
            for short_code in short_codes:
                assert Link.objects.filter(short_code=short_code).exists(), \
                    f"Link {short_code} should still exist"
            
            # Verify links are still accessible
            redirect_client = APIClient()
            for short_code in short_codes:
                redirect_response = redirect_client.get(
                    f'/r/{short_code}',
                    follow=False
                )
                assert redirect_response.status_code == 302, \
                    f"Link {short_code} should still redirect"
        
        finally:
            # Cleanup
            Link.objects.filter(user__in=[user1, user2]).delete()
            user1.delete()
            user2.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        urls=st.lists(
            valid_url_strategy(),
            min_size=1,
            max_size=3,
            unique=True
        )
    )
    def test_batch_delete_partial_success_with_nonexistent(self, urls):
        """
        Feature: url-shortener, Property 22: 批量删除完整性
        Validates: Requirements 9.3
        
        Batch delete with mix of existing and non-existing codes
        should delete existing ones and report errors for non-existing.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create links
            links_data = [{'original_url': url} for url in urls]
            create_response = client.post('/api/links/batch/', {
                'links': links_data
            }, format='json')
            
            assert create_response.status_code == 201
            
            existing_codes = [
                result['short_code'] 
                for result in create_response.data['results']
                if result['success']
            ]
            
            # Add non-existent codes
            nonexistent_codes = ['nonex1', 'nonex2']
            all_codes = existing_codes + nonexistent_codes
            
            # Batch delete
            delete_response = client.post('/api/links/batch/delete/', {
                'short_codes': all_codes
            }, format='json')
            
            assert delete_response.status_code == 200
            
            # Existing should succeed, non-existing should fail
            assert delete_response.data['successful'] == len(existing_codes)
            assert delete_response.data['failed'] == len(nonexistent_codes)
            
            # Verify existing links are deleted
            for short_code in existing_codes:
                assert not Link.objects.filter(short_code=short_code).exists()
            
            # Check individual results
            for result in delete_response.data['results']:
                if result['short_code'] in existing_codes:
                    assert result['success'] is True
                else:
                    assert result['success'] is False
                    assert result['error'] is not None
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()
