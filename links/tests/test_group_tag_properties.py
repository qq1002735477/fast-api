"""
Property-based tests for group and tag management.

Feature: url-shortener
Uses hypothesis library for property-based testing.
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
import string
import uuid

from links.models import Link, Group, Tag

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


def group_name_strategy():
    """Generate valid group names that won't trigger SQL injection detection."""
    return st.text(
        alphabet=string.ascii_letters + string.digits,
        min_size=1,
        max_size=50
    ).map(lambda x: x.strip()).filter(lambda x: len(x) > 0)


def tag_name_strategy():
    """Generate valid tag names that won't trigger SQL injection detection."""
    return st.text(
        alphabet=string.ascii_letters + string.digits,
        min_size=1,
        max_size=30
    ).filter(lambda x: x.strip() and len(x.strip()) > 0)


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
class TestGroupTagManagementRoundtrip:
    """
    Property 23: Group and Tag Management Roundtrip
    
    For any group and tag:
    - After creation, they should be queryable
    - After assigning a link to a group or adding tags, querying the link should reflect the association
    
    Validates: Requirements 10.1, 10.2, 10.3
    """

    @settings(max_examples=100, deadline=None)
    @given(
        group_name=group_name_strategy(),
        description=st.text(
            alphabet=string.ascii_letters + string.digits + ' .,!?',
            max_size=100
        ).map(lambda x: x.strip())
    )
    def test_group_create_query_roundtrip(self, group_name, description):
        """
        Feature: url-shortener, Property 23: 分组标签管理往返
        Validates: Requirements 10.1
        
        For any group, creating it and then querying should return the same data.
        """
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a group
            create_response = client.post('/api/groups/', {
                'name': group_name,
                'description': description,
            }, format='json')
            
            assert create_response.status_code == 201, \
                f"Group creation failed: {create_response.data}"
            
            group_id = create_response.data['id']
            
            # Query the group
            get_response = client.get(f'/api/groups/{group_id}/')
            
            assert get_response.status_code == 200, \
                f"Group query failed: {get_response.data}"
            assert get_response.data['name'] == group_name
            # Description may be stripped of whitespace
            assert get_response.data['description'].strip() == description.strip()
            
        finally:
            Group.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(tag_name=tag_name_strategy())
    def test_tag_create_query_roundtrip(self, tag_name):
        """
        Feature: url-shortener, Property 23: 分组标签管理往返
        Validates: Requirements 10.3
        
        For any tag, creating it and then querying should return the same data.
        """
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a tag
            create_response = client.post('/api/tags/', {
                'name': tag_name,
            }, format='json')
            
            assert create_response.status_code == 201, \
                f"Tag creation failed: {create_response.data}"
            
            tag_id = create_response.data['id']
            
            # Query all tags and find the created one
            list_response = client.get('/api/tags/')
            
            assert list_response.status_code == 200
            # Handle both paginated and non-paginated responses
            tags_data = list_response.data
            if isinstance(tags_data, dict) and 'results' in tags_data:
                tags_data = tags_data['results']
            
            tag_names = [t['name'] for t in tags_data]
            assert tag_name in tag_names, \
                f"Created tag '{tag_name}' not found in list"
            
        finally:
            Tag.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        group_name=group_name_strategy()
    )
    def test_link_group_assignment_roundtrip(self, url, group_name):
        """
        Feature: url-shortener, Property 23: 分组标签管理往返
        Validates: Requirements 10.2
        
        For any link assigned to a group, querying the link should reflect the group association.
        """
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a group first
            group_response = client.post('/api/groups/', {
                'name': group_name,
                'description': 'Test group',
            }, format='json')
            
            assert group_response.status_code == 201
            group_id = group_response.data['id']
            
            # Create a link with the group
            link_response = client.post('/api/links/', {
                'original_url': url,
                'group_id': group_id,
            }, format='json')
            
            assert link_response.status_code == 201, \
                f"Link creation failed: {link_response.data}"
            
            short_code = link_response.data['short_code']
            
            # Query the link and verify group association
            get_response = client.get(f'/api/links/{short_code}/')
            
            assert get_response.status_code == 200
            assert get_response.data['group'] is not None
            assert get_response.data['group']['id'] == group_id
            assert get_response.data['group']['name'] == group_name
            
        finally:
            Link.objects.filter(user=user).delete()
            Group.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        tag_name=tag_name_strategy()
    )
    def test_link_tag_assignment_roundtrip(self, url, tag_name):
        """
        Feature: url-shortener, Property 23: 分组标签管理往返
        Validates: Requirements 10.3
        
        For any link with tags, querying the link should reflect the tag association.
        """
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a tag first
            tag_response = client.post('/api/tags/', {
                'name': tag_name,
            }, format='json')
            
            assert tag_response.status_code == 201
            tag_id = tag_response.data['id']
            
            # Create a link with the tag
            link_response = client.post('/api/links/', {
                'original_url': url,
                'tag_ids': [tag_id],
            }, format='json')
            
            assert link_response.status_code == 201, \
                f"Link creation failed: {link_response.data}"
            
            short_code = link_response.data['short_code']
            
            # Query the link and verify tag association
            get_response = client.get(f'/api/links/{short_code}/')
            
            assert get_response.status_code == 200
            assert len(get_response.data['tags']) == 1
            assert get_response.data['tags'][0]['id'] == tag_id
            assert get_response.data['tags'][0]['name'] == tag_name
            
        finally:
            Link.objects.filter(user=user).delete()
            Tag.objects.filter(user=user).delete()
            user.delete()



@pytest.mark.django_db(transaction=True)
class TestGroupTagFiltering:
    """
    Property 24: Group and Tag Filtering
    
    For any set of links with groups or tags, filtering by group or tag
    should only return matching links.
    
    Validates: Requirements 10.4
    """

    @settings(max_examples=100, deadline=None)
    @given(
        url1=valid_url_strategy(),
        url2=valid_url_strategy(),
        group_name=group_name_strategy()
    )
    def test_filter_by_group_returns_only_matching_links(self, url1, url2, group_name):
        """
        Feature: url-shortener, Property 24: 分组标签筛选
        Validates: Requirements 10.4
        
        For any links with different groups, filtering by group should only return matching links.
        """
        # Ensure URLs are different
        assume(url1 != url2)
        
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a group
            group_response = client.post('/api/groups/', {
                'name': group_name,
                'description': 'Test group',
            }, format='json')
            
            assert group_response.status_code == 201
            group_id = group_response.data['id']
            
            # Create link1 with the group
            link1_response = client.post('/api/links/', {
                'original_url': url1,
                'group_id': group_id,
            }, format='json')
            
            assert link1_response.status_code == 201
            link1_code = link1_response.data['short_code']
            
            # Create link2 without a group
            link2_response = client.post('/api/links/', {
                'original_url': url2,
            }, format='json')
            
            assert link2_response.status_code == 201
            link2_code = link2_response.data['short_code']
            
            # Filter by group_id
            filter_response = client.get(f'/api/links/?group_id={group_id}')
            
            assert filter_response.status_code == 200
            
            # Handle paginated response
            results = filter_response.data
            if isinstance(results, dict) and 'results' in results:
                results = results['results']
            
            # Should only contain link1
            short_codes = [link['short_code'] for link in results]
            assert link1_code in short_codes, \
                f"Link with group should be in filtered results"
            assert link2_code not in short_codes, \
                f"Link without group should not be in filtered results"
            
        finally:
            Link.objects.filter(user=user).delete()
            Group.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url1=valid_url_strategy(),
        url2=valid_url_strategy(),
        tag_name=tag_name_strategy()
    )
    def test_filter_by_tag_returns_only_matching_links(self, url1, url2, tag_name):
        """
        Feature: url-shortener, Property 24: 分组标签筛选
        Validates: Requirements 10.4
        
        For any links with different tags, filtering by tag should only return matching links.
        """
        # Ensure URLs are different
        assume(url1 != url2)
        
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a tag
            tag_response = client.post('/api/tags/', {
                'name': tag_name,
            }, format='json')
            
            assert tag_response.status_code == 201
            tag_id = tag_response.data['id']
            
            # Create link1 with the tag
            link1_response = client.post('/api/links/', {
                'original_url': url1,
                'tag_ids': [tag_id],
            }, format='json')
            
            assert link1_response.status_code == 201
            link1_code = link1_response.data['short_code']
            
            # Create link2 without tags
            link2_response = client.post('/api/links/', {
                'original_url': url2,
            }, format='json')
            
            assert link2_response.status_code == 201
            link2_code = link2_response.data['short_code']
            
            # Filter by tag_id
            filter_response = client.get(f'/api/links/?tag_id={tag_id}')
            
            assert filter_response.status_code == 200
            
            # Handle paginated response
            results = filter_response.data
            if isinstance(results, dict) and 'results' in results:
                results = results['results']
            
            # Should only contain link1
            short_codes = [link['short_code'] for link in results]
            assert link1_code in short_codes, \
                f"Link with tag should be in filtered results"
            assert link2_code not in short_codes, \
                f"Link without tag should not be in filtered results"
            
        finally:
            Link.objects.filter(user=user).delete()
            Tag.objects.filter(user=user).delete()
            user.delete()



@pytest.mark.django_db(transaction=True)
class TestGroupDeletionPreservesLinks:
    """
    Property 25: Group Deletion Preserves Links
    
    For any group containing links, deleting the group should preserve
    the links but set their group field to null.
    
    Validates: Requirements 10.5
    """

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        group_name=group_name_strategy()
    )
    def test_group_deletion_preserves_links(self, url, group_name):
        """
        Feature: url-shortener, Property 25: 分组删除保留链接
        Validates: Requirements 10.5
        
        For any group with links, deleting the group should preserve links with null group.
        """
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a group
            group_response = client.post('/api/groups/', {
                'name': group_name,
                'description': 'Test group',
            }, format='json')
            
            assert group_response.status_code == 201
            group_id = group_response.data['id']
            
            # Create a link with the group
            link_response = client.post('/api/links/', {
                'original_url': url,
                'group_id': group_id,
            }, format='json')
            
            assert link_response.status_code == 201
            short_code = link_response.data['short_code']
            
            # Verify link has the group
            get_response = client.get(f'/api/links/{short_code}/')
            assert get_response.status_code == 200
            assert get_response.data['group'] is not None
            assert get_response.data['group']['id'] == group_id
            
            # Delete the group
            delete_response = client.delete(f'/api/groups/{group_id}/')
            assert delete_response.status_code == 204
            
            # Verify link still exists but group is null
            get_response_after = client.get(f'/api/links/{short_code}/')
            assert get_response_after.status_code == 200, \
                f"Link should still exist after group deletion"
            assert get_response_after.data['group'] is None, \
                f"Link's group should be null after group deletion"
            assert get_response_after.data['original_url'] == url, \
                f"Link's original URL should be preserved"
            
        finally:
            Link.objects.filter(user=user).delete()
            Group.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        urls=st.lists(valid_url_strategy(), min_size=2, max_size=5, unique=True),
        group_name=group_name_strategy()
    )
    def test_group_deletion_preserves_multiple_links(self, urls, group_name):
        """
        Feature: url-shortener, Property 25: 分组删除保留链接
        Validates: Requirements 10.5
        
        For any group with multiple links, deleting the group should preserve all links.
        """
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create a group
            group_response = client.post('/api/groups/', {
                'name': group_name,
                'description': 'Test group',
            }, format='json')
            
            assert group_response.status_code == 201
            group_id = group_response.data['id']
            
            # Create multiple links with the group
            short_codes = []
            for url in urls:
                link_response = client.post('/api/links/', {
                    'original_url': url,
                    'group_id': group_id,
                }, format='json')
                
                assert link_response.status_code == 201
                short_codes.append(link_response.data['short_code'])
            
            # Delete the group
            delete_response = client.delete(f'/api/groups/{group_id}/')
            assert delete_response.status_code == 204
            
            # Verify all links still exist with null group
            for i, short_code in enumerate(short_codes):
                get_response = client.get(f'/api/links/{short_code}/')
                assert get_response.status_code == 200, \
                    f"Link {short_code} should still exist after group deletion"
                assert get_response.data['group'] is None, \
                    f"Link {short_code}'s group should be null after group deletion"
                assert get_response.data['original_url'] == urls[i], \
                    f"Link {short_code}'s original URL should be preserved"
            
        finally:
            Link.objects.filter(user=user).delete()
            Group.objects.filter(user=user).delete()
            user.delete()

