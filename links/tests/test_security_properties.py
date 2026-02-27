"""
Property-based tests for security features.

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
from links.security import url_security_service, DEFAULT_MALICIOUS_DOMAINS

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


def malicious_domain_strategy():
    """Generate URLs with malicious domains from the blacklist."""
    protocols = st.sampled_from(['http', 'https'])
    domains = st.sampled_from(list(DEFAULT_MALICIOUS_DOMAINS))
    paths = st.text(
        alphabet=string.ascii_lowercase + string.digits + '-_/',
        min_size=0,
        max_size=30
    )
    
    return st.builds(
        lambda p, d, path: f'{p}://{d}/{path}' if path else f'{p}://{d}',
        protocols, domains, paths
    )


def safe_domain_strategy():
    """Generate URLs with safe domains (not in blacklist)."""
    protocols = st.sampled_from(['http', 'https'])
    safe_domains = st.sampled_from([
        'example.com', 'test.org', 'sample.net', 'demo.io',
        'mysite.com', 'website.org', 'page.net', 'google.com',
        'github.com', 'stackoverflow.com'
    ])
    paths = st.text(
        alphabet=string.ascii_lowercase + string.digits + '-_',
        min_size=0,
        max_size=30
    ).map(lambda x: f'/{x}' if x else '')
    
    return st.builds(
        lambda p, d, path: f'{p}://{d}{path}',
        protocols, safe_domains, paths
    )


@pytest.mark.django_db(transaction=True)
class TestMaliciousURLRejection:
    """
    Property 26: Malicious URL Rejection
    
    For any URL with a domain in the malicious blacklist,
    the link creation request should be rejected.
    
    Validates: Requirements 11.1, 11.2
    """

    @settings(max_examples=100, deadline=None)
    @given(malicious_url=malicious_domain_strategy())
    def test_malicious_url_rejected(self, malicious_url):
        """
        Feature: url-shortener, Property 26: 恶意 URL 拒绝
        Validates: Requirements 11.1, 11.2
        
        For any URL with a blacklisted domain, link creation should be rejected.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Try to create link with malicious URL
            response = client.post('/api/links/', {
                'original_url': malicious_url,
            }, format='json')
            
            # Should be rejected with 400
            assert response.status_code == 400, \
                f"Expected 400 for malicious URL '{malicious_url}', got {response.status_code}"
            
            # Verify error message mentions URL rejection
            assert 'original_url' in response.data or 'error' in response.data, \
                f"Expected error about URL, got {response.data}"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(safe_url=safe_domain_strategy())
    def test_safe_url_accepted(self, safe_url):
        """
        Feature: url-shortener, Property 26: 恶意 URL 拒绝
        Validates: Requirements 11.1, 11.2
        
        For any URL with a safe domain, link creation should succeed.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create link with safe URL
            response = client.post('/api/links/', {
                'original_url': safe_url,
            }, format='json')
            
            # Should succeed with 201 or 200 (if already exists)
            assert response.status_code in [200, 201], \
                f"Expected 200/201 for safe URL '{safe_url}', got {response.status_code}: {response.data}"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=50, deadline=None)
    @given(malicious_url=malicious_domain_strategy())
    def test_malicious_url_in_batch_rejected(self, malicious_url):
        """
        Feature: url-shortener, Property 26: 恶意 URL 拒绝
        Validates: Requirements 11.1, 11.2
        
        For any malicious URL in batch creation, that specific URL should be rejected.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Try batch creation with malicious URL
            response = client.post('/api/links/batch/', {
                'links': [
                    {'original_url': malicious_url},
                ]
            }, format='json')
            
            # Batch should process but mark the malicious URL as failed
            assert response.status_code in [201, 400], \
                f"Unexpected status {response.status_code}"
            
            if response.status_code == 201:
                # Check that the malicious URL failed
                results = response.data.get('results', [])
                assert len(results) > 0, "Expected results in response"
                assert results[0]['success'] is False, \
                    f"Expected malicious URL to fail, got {results[0]}"
        
        finally:
            # Cleanup
            Link.objects.filter(user=user).delete()
            user.delete()


@pytest.mark.django_db(transaction=True)
class TestURLSecurityService:
    """
    Unit tests for the URL security service.
    
    Validates: Requirements 11.1, 11.2
    """

    def test_blacklisted_domain_detected(self):
        """Test that blacklisted domains are correctly detected."""
        for domain in list(DEFAULT_MALICIOUS_DOMAINS)[:5]:
            url = f'https://{domain}/path'
            assert not url_security_service.is_url_safe(url), \
                f"Expected {url} to be detected as unsafe"

    def test_subdomain_of_blacklisted_detected(self):
        """Test that subdomains of blacklisted domains are detected."""
        for domain in list(DEFAULT_MALICIOUS_DOMAINS)[:3]:
            url = f'https://sub.{domain}/path'
            assert not url_security_service.is_url_safe(url), \
                f"Expected subdomain {url} to be detected as unsafe"

    def test_safe_domain_allowed(self):
        """Test that safe domains are allowed."""
        safe_urls = [
            'https://example.com/path',
            'https://google.com',
            'https://github.com/user/repo',
        ]
        for url in safe_urls:
            assert url_security_service.is_url_safe(url), \
                f"Expected {url} to be safe"

    def test_domain_extraction(self):
        """Test domain extraction from URLs."""
        test_cases = [
            ('https://example.com/path', 'example.com'),
            ('http://www.example.com', 'example.com'),
            ('https://sub.example.com:8080/path', 'sub.example.com'),
        ]
        for url, expected_domain in test_cases:
            domain = url_security_service.extract_domain(url)
            assert domain == expected_domain, \
                f"Expected domain '{expected_domain}' from '{url}', got '{domain}'"



def xss_payload_strategy():
    """Generate strings containing XSS attack patterns."""
    xss_patterns = [
        '<script>alert("xss")</script>',
        '<img src=x onerror=alert("xss")>',
        'javascript:alert("xss")',
        '<svg onload=alert("xss")>',
        '<iframe src="javascript:alert(1)">',
        '<body onload=alert("xss")>',
        '<input onfocus=alert("xss") autofocus>',
        '<marquee onstart=alert("xss")>',
        '<object data="javascript:alert(1)">',
        '<embed src="javascript:alert(1)">',
        'data:text/html,<script>alert("xss")</script>',
        'vbscript:msgbox("xss")',
    ]
    return st.sampled_from(xss_patterns)


def sql_injection_strategy():
    """Generate strings containing SQL injection patterns."""
    sql_patterns = [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
        "1; DELETE FROM links",
        "' UNION SELECT * FROM users --",
        "admin'--",
        "1' OR 1=1 --",
        "'; TRUNCATE TABLE links; --",
        "' OR ''='",
        "1; UPDATE users SET password='hacked'",
        "'; exec xp_cmdshell('dir'); --",
    ]
    return st.sampled_from(sql_patterns)


def safe_input_strategy():
    """Generate safe input strings without malicious patterns."""
    return st.text(
        alphabet=string.ascii_letters + string.digits + ' _.',
        min_size=1,
        max_size=50
    ).filter(lambda x: x.strip() and len(x.strip()) > 0)  # Filter out whitespace-only strings


@pytest.mark.django_db(transaction=True)
class TestInputSanitization:
    """
    Property 27: Input Sanitization
    
    For any input containing potential XSS or SQL injection patterns,
    the system should correctly sanitize or reject the input.
    
    Validates: Requirements 11.5
    """

    @settings(max_examples=100, deadline=None)
    @given(xss_payload=xss_payload_strategy())
    def test_xss_detected_in_tag_name(self, xss_payload):
        """
        Feature: url-shortener, Property 27: 输入清理
        Validates: Requirements 11.5
        
        For any XSS payload in tag name, creation should be rejected.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Try to create tag with XSS payload
            response = client.post('/api/tags/', {
                'name': xss_payload,
            }, format='json')
            
            # Should be rejected with 400
            assert response.status_code == 400, \
                f"Expected 400 for XSS payload '{xss_payload[:30]}...', got {response.status_code}"
        
        finally:
            # Cleanup
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(xss_payload=xss_payload_strategy())
    def test_xss_detected_in_group_name(self, xss_payload):
        """
        Feature: url-shortener, Property 27: 输入清理
        Validates: Requirements 11.5
        
        For any XSS payload in group name, creation should be rejected.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Try to create group with XSS payload
            response = client.post('/api/groups/', {
                'name': xss_payload,
            }, format='json')
            
            # Should be rejected with 400
            assert response.status_code == 400, \
                f"Expected 400 for XSS payload '{xss_payload[:30]}...', got {response.status_code}"
        
        finally:
            # Cleanup
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(sql_payload=sql_injection_strategy())
    def test_sql_injection_detected_in_tag_name(self, sql_payload):
        """
        Feature: url-shortener, Property 27: 输入清理
        Validates: Requirements 11.5
        
        For any SQL injection payload in tag name, creation should be rejected.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Try to create tag with SQL injection payload
            response = client.post('/api/tags/', {
                'name': sql_payload,
            }, format='json')
            
            # Should be rejected with 400
            assert response.status_code == 400, \
                f"Expected 400 for SQL injection '{sql_payload[:30]}...', got {response.status_code}"
        
        finally:
            # Cleanup
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(sql_payload=sql_injection_strategy())
    def test_sql_injection_detected_in_group_description(self, sql_payload):
        """
        Feature: url-shortener, Property 27: 输入清理
        Validates: Requirements 11.5
        
        For any SQL injection payload in group description, creation should be rejected.
        """
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Try to create group with SQL injection in description
            response = client.post('/api/groups/', {
                'name': 'Test Group',
                'description': sql_payload,
            }, format='json')
            
            # Should be rejected with 400
            assert response.status_code == 400, \
                f"Expected 400 for SQL injection '{sql_payload[:30]}...', got {response.status_code}"
        
        finally:
            # Cleanup
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(safe_input=safe_input_strategy())
    def test_safe_input_accepted_in_tag(self, safe_input):
        """
        Feature: url-shortener, Property 27: 输入清理
        Validates: Requirements 11.5
        
        For any safe input, tag creation should succeed.
        """
        from links.models import Tag
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create tag with safe input
            response = client.post('/api/tags/', {
                'name': safe_input,
            }, format='json')
            
            # Should succeed with 201
            assert response.status_code == 201, \
                f"Expected 201 for safe input '{safe_input}', got {response.status_code}: {response.data}"
        
        finally:
            # Cleanup
            Tag.objects.filter(user=user).delete()
            user.delete()

    @settings(max_examples=100, deadline=None)
    @given(safe_input=safe_input_strategy())
    def test_safe_input_accepted_in_group(self, safe_input):
        """
        Feature: url-shortener, Property 27: 输入清理
        Validates: Requirements 11.5
        
        For any safe input, group creation should succeed.
        """
        from links.models import Group
        
        # Create a test user
        user = create_test_user()
        client = get_authenticated_client(user)
        
        try:
            # Create group with safe input
            response = client.post('/api/groups/', {
                'name': safe_input,
                'description': f'Description for {safe_input}',
            }, format='json')
            
            # Should succeed with 201
            assert response.status_code == 201, \
                f"Expected 201 for safe input '{safe_input}', got {response.status_code}: {response.data}"
        
        finally:
            # Cleanup
            Group.objects.filter(user=user).delete()
            user.delete()


@pytest.mark.django_db(transaction=True)
class TestInputSanitizationService:
    """
    Unit tests for the input sanitization service.
    
    Validates: Requirements 11.5
    """

    def test_xss_patterns_detected(self):
        """Test that XSS patterns are correctly detected."""
        xss_inputs = [
            '<script>alert("xss")</script>',
            '<img src=x onerror=alert(1)>',
            'javascript:alert(1)',
            '<svg onload=alert(1)>',
        ]
        for input_str in xss_inputs:
            assert url_security_service.contains_xss(input_str), \
                f"Expected XSS detection for: {input_str}"

    def test_sql_injection_patterns_detected(self):
        """Test that SQL injection patterns are correctly detected."""
        sql_inputs = [
            "' OR '1'='1",
            "; DROP TABLE users; --",
            "' UNION SELECT * FROM users",
            "'; exec xp_cmdshell('dir')",
        ]
        for input_str in sql_inputs:
            assert url_security_service.contains_sql_injection(input_str), \
                f"Expected SQL injection detection for: {input_str}"

    def test_safe_input_not_flagged(self):
        """Test that safe inputs are not flagged as malicious."""
        safe_inputs = [
            'Hello World',
            'My Tag Name',
            'Group Description 123',
            'test-name_with.dots',
        ]
        for input_str in safe_inputs:
            result = url_security_service.validate_input(input_str)
            assert result['is_valid'], \
                f"Expected safe input '{input_str}' to be valid"

    def test_html_escaping(self):
        """Test that HTML special characters are escaped."""
        test_cases = [
            ('<script>', '&lt;script&gt;'),
            ('"test"', '&quot;test&quot;'),
            ("'test'", '&#x27;test&#x27;'),
            ('a & b', 'a &amp; b'),
        ]
        for input_str, expected in test_cases:
            sanitized = url_security_service.sanitize_input(input_str)
            assert sanitized == expected, \
                f"Expected '{expected}' for '{input_str}', got '{sanitized}'"
