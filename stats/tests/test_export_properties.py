"""
Property-based tests for data export functionality.

Feature: url-shortener
Uses hypothesis library for property-based testing.

Property 28: Data Export Integrity
For any user's link data, the exported CSV should contain all links
with their details (short code, original URL, creation date, click count, tags).

Validates: Requirements 12.1, 12.3
"""
import csv
import io
import os
import pytest
from hypothesis import given, strategies as st, settings, assume
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
import string
import uuid

from links.models import Link, Group, Tag, AccessLog
from stats.models import ExportTask

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


def tag_name_strategy():
    """Generate valid tag names."""
    return st.text(
        alphabet=string.ascii_lowercase + string.digits,
        min_size=2,
        max_size=20
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
class TestDataExportIntegrity:
    """
    Property 28: Data Export Integrity
    
    For any user's link data, the exported CSV should contain all links
    with their details (short code, original URL, creation date, click count, tags).
    
    Validates: Requirements 12.1, 12.3
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
    def test_export_contains_all_links(self, urls):
        """
        Feature: url-shortener, Property 28: 数据导出完整性
        Validates: Requirements 12.1, 12.3
        
        For any set of links created by a user, the export should
        contain exactly all those links.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create links
            created_short_codes = []
            for url in urls:
                response = client.post('/api/links/', {
                    'original_url': url,
                }, format='json')
                
                assert response.status_code == 201, \
                    f"Link creation failed: {response.data}"
                created_short_codes.append(response.data['short_code'])
            
            # Request export
            export_response = client.post('/api/export/create/', format='json')
            
            assert export_response.status_code == 201, \
                f"Export creation failed: {export_response.data}"
            
            task_id = export_response.data['id']
            
            # Check export status (should be completed for small datasets)
            status_response = client.get(f'/api/export/{task_id}/')
            assert status_response.status_code == 200
            
            # Wait for completion if processing
            if status_response.data['status'] == 'processing':
                import time
                for _ in range(10):
                    time.sleep(0.5)
                    status_response = client.get(f'/api/export/{task_id}/')
                    if status_response.data['status'] in ['completed', 'failed']:
                        break
            
            assert status_response.data['status'] == 'completed', \
                f"Export failed with status: {status_response.data['status']}"
            
            # Download the export
            download_response = client.get(f'/api/export/{task_id}/download/')
            assert download_response.status_code == 200
            
            # Parse CSV content
            content = b''.join(download_response.streaming_content).decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))
            exported_rows = list(reader)
            
            # Verify all links are in export
            exported_short_codes = [row['short_code'] for row in exported_rows]
            
            assert len(exported_rows) == len(urls), \
                f"Expected {len(urls)} rows, got {len(exported_rows)}"
            
            for short_code in created_short_codes:
                assert short_code in exported_short_codes, \
                    f"Short code {short_code} not found in export"
            
            # Verify each row has required fields
            required_fields = [
                'short_code', 'original_url', 'created_at',
                'click_count', 'tags'
            ]
            for row in exported_rows:
                for field in required_fields:
                    assert field in row, \
                        f"Required field '{field}' missing from export"
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            ExportTask.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        tag_names=st.lists(
            tag_name_strategy(),
            min_size=1,
            max_size=3,
            unique=True
        )
    )
    def test_export_includes_tags(self, url, tag_names):
        """
        Feature: url-shortener, Property 28: 数据导出完整性
        Validates: Requirements 12.1, 12.3
        
        For any link with tags, the export should include all tag names.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create tags
            tag_ids = []
            for tag_name in tag_names:
                tag_response = client.post('/api/tags/', {
                    'name': tag_name,
                }, format='json')
                
                if tag_response.status_code == 201:
                    tag_ids.append(tag_response.data['id'])
            
            assume(len(tag_ids) > 0)
            
            # Create link with tags
            link_response = client.post('/api/links/', {
                'original_url': url,
                'tag_ids': tag_ids,
            }, format='json')
            
            assert link_response.status_code == 201, \
                f"Link creation failed: {link_response.data}"
            
            short_code = link_response.data['short_code']
            
            # Request export
            export_response = client.post('/api/export/create/', format='json')
            assert export_response.status_code == 201
            
            task_id = export_response.data['id']
            
            # Check status
            status_response = client.get(f'/api/export/{task_id}/')
            assert status_response.data['status'] == 'completed'
            
            # Download the export
            download_response = client.get(f'/api/export/{task_id}/download/')
            assert download_response.status_code == 200
            
            # Parse CSV content
            content = b''.join(download_response.streaming_content).decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))
            exported_rows = list(reader)
            
            # Find the row for our link
            link_row = None
            for row in exported_rows:
                if row['short_code'] == short_code:
                    link_row = row
                    break
            
            assert link_row is not None, \
                f"Link {short_code} not found in export"
            
            # Verify tags are included
            exported_tags = link_row['tags'].split(',') if link_row['tags'] else []
            exported_tags = [t.strip() for t in exported_tags if t.strip()]
            
            # Get actual tag names from database
            link = Link.objects.get(short_code=short_code)
            actual_tag_names = list(link.tags.values_list('name', flat=True))
            
            assert set(exported_tags) == set(actual_tag_names), \
                f"Exported tags {exported_tags} != actual tags {actual_tag_names}"
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            Tag.objects.filter(user=user).delete()
            ExportTask.objects.filter(user=user).delete()
            user.delete()


    @settings(max_examples=100, deadline=None)
    @given(
        url=valid_url_strategy(),
        access_count=st.integers(min_value=0, max_value=5)
    )
    def test_export_includes_click_count(self, url, access_count):
        """
        Feature: url-shortener, Property 28: 数据导出完整性
        Validates: Requirements 12.1, 12.3
        
        For any link, the export should include the correct click count.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create link
            link_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert link_response.status_code == 201
            short_code = link_response.data['short_code']
            
            # Access the link to generate clicks
            redirect_client = APIClient()
            for _ in range(access_count):
                redirect_response = redirect_client.get(
                    f'/r/{short_code}',
                    follow=False
                )
                assert redirect_response.status_code == 302
            
            # Request export
            export_response = client.post('/api/export/create/', format='json')
            assert export_response.status_code == 201
            
            task_id = export_response.data['id']
            
            # Check status
            status_response = client.get(f'/api/export/{task_id}/')
            assert status_response.data['status'] == 'completed'
            
            # Download the export
            download_response = client.get(f'/api/export/{task_id}/download/')
            assert download_response.status_code == 200
            
            # Parse CSV content
            content = b''.join(download_response.streaming_content).decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))
            exported_rows = list(reader)
            
            # Find the row for our link
            link_row = None
            for row in exported_rows:
                if row['short_code'] == short_code:
                    link_row = row
                    break
            
            assert link_row is not None, \
                f"Link {short_code} not found in export"
            
            # Verify click count matches
            exported_click_count = int(link_row['click_count'])
            assert exported_click_count == access_count, \
                f"Exported click count {exported_click_count} != actual {access_count}"
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            ExportTask.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(
        urls=st.lists(
            valid_url_strategy(),
            min_size=1,
            max_size=3,
            unique=True
        )
    )
    def test_export_original_urls_match(self, urls):
        """
        Feature: url-shortener, Property 28: 数据导出完整性
        Validates: Requirements 12.1, 12.3
        
        For any set of links, the exported original URLs should match
        the URLs used to create the links.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create links and track short_code -> url mapping
            url_mapping = {}
            for url in urls:
                response = client.post('/api/links/', {
                    'original_url': url,
                }, format='json')
                
                assert response.status_code == 201
                url_mapping[response.data['short_code']] = url
            
            # Request export
            export_response = client.post('/api/export/create/', format='json')
            assert export_response.status_code == 201
            
            task_id = export_response.data['id']
            
            # Check status
            status_response = client.get(f'/api/export/{task_id}/')
            assert status_response.data['status'] == 'completed'
            
            # Download the export
            download_response = client.get(f'/api/export/{task_id}/download/')
            assert download_response.status_code == 200
            
            # Parse CSV content
            content = b''.join(download_response.streaming_content).decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))
            exported_rows = list(reader)
            
            # Verify each exported URL matches the original
            for row in exported_rows:
                short_code = row['short_code']
                exported_url = row['original_url']
                
                assert short_code in url_mapping, \
                    f"Unexpected short code {short_code} in export"
                
                assert exported_url == url_mapping[short_code], \
                    f"URL mismatch for {short_code}: {exported_url} != {url_mapping[short_code]}"
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            ExportTask.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(url=valid_url_strategy())
    def test_export_includes_creation_date(self, url):
        """
        Feature: url-shortener, Property 28: 数据导出完整性
        Validates: Requirements 12.1, 12.3
        
        For any link, the export should include a valid creation date.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create link
            link_response = client.post('/api/links/', {
                'original_url': url,
            }, format='json')
            
            assert link_response.status_code == 201
            short_code = link_response.data['short_code']
            
            # Get the actual creation date from database
            link = Link.objects.get(short_code=short_code)
            actual_created_at = link.created_at
            
            # Request export
            export_response = client.post('/api/export/create/', format='json')
            assert export_response.status_code == 201
            
            task_id = export_response.data['id']
            
            # Check status
            status_response = client.get(f'/api/export/{task_id}/')
            assert status_response.data['status'] == 'completed'
            
            # Download the export
            download_response = client.get(f'/api/export/{task_id}/download/')
            assert download_response.status_code == 200
            
            # Parse CSV content
            content = b''.join(download_response.streaming_content).decode('utf-8')
            reader = csv.DictReader(io.StringIO(content))
            exported_rows = list(reader)
            
            # Find the row for our link
            link_row = None
            for row in exported_rows:
                if row['short_code'] == short_code:
                    link_row = row
                    break
            
            assert link_row is not None
            
            # Verify creation date is present and valid
            exported_created_at = link_row['created_at']
            assert exported_created_at, "Creation date should not be empty"
            
            # Parse and compare dates (format: YYYY-MM-DD HH:MM:SS)
            from datetime import datetime
            parsed_date = datetime.strptime(exported_created_at, '%Y-%m-%d %H:%M:%S')
            
            # Compare date components (ignoring microseconds)
            assert parsed_date.year == actual_created_at.year
            assert parsed_date.month == actual_created_at.month
            assert parsed_date.day == actual_created_at.day
            assert parsed_date.hour == actual_created_at.hour
            assert parsed_date.minute == actual_created_at.minute
        
        finally:
            # Cleanup
            AccessLog.objects.filter(link__user=user).delete()
            Link.objects.filter(user=user).delete()
            ExportTask.objects.filter(user=user).delete()
            user.delete()
