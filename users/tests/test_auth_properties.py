"""
Property-based tests for user authentication.

Feature: url-shortener
Uses hypothesis library for property-based testing.
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
import string

User = get_user_model()


# Custom strategies for generating valid user data
def valid_username_strategy():
    """Generate valid usernames: 3-30 alphanumeric characters."""
    return st.text(
        alphabet=string.ascii_letters + string.digits,
        min_size=3,
        max_size=30
    ).filter(lambda x: x and x[0].isalpha())


def valid_email_strategy():
    """Generate valid email addresses."""
    local_part = st.text(
        alphabet=string.ascii_lowercase + string.digits,
        min_size=3,
        max_size=20
    ).filter(lambda x: x and x[0].isalpha())
    domain = st.sampled_from(['example.com', 'test.org', 'mail.net'])
    return st.builds(lambda l, d: f"{l}@{d}", local_part, domain)


def valid_password_strategy():
    """Generate valid passwords: 8+ chars with letters and digits."""
    return st.text(
        alphabet=string.ascii_letters + string.digits + '!@#$%',
        min_size=8,
        max_size=30
    ).filter(lambda x: (
        any(c.isalpha() for c in x) and 
        any(c.isdigit() for c in x) and
        len(x) >= 8
    ))


@pytest.mark.django_db(transaction=True)
class TestRegistrationLoginRoundtrip:
    """
    Property 1: Registration-Login Roundtrip
    
    For any valid registration data (username, email, password),
    registering and then logging in with the same credentials should
    successfully return JWT tokens.
    
    Validates: Requirements 1.1, 1.3
    """

    @settings(max_examples=100, deadline=None)
    @given(
        username=valid_username_strategy(),
        email=valid_email_strategy(),
        password=valid_password_strategy()
    )
    def test_register_login_roundtrip(self, username, email, password):
        """
        Feature: url-shortener, Property 1: 注册-登录往返
        Validates: Requirements 1.1, 1.3
        
        For any valid registration data, registering then logging in
        with the same credentials should succeed and return tokens.
        """
        # Ensure unique test data
        assume(not User.objects.filter(username=username).exists())
        assume(not User.objects.filter(email=email).exists())
        
        client = APIClient()
        
        # Step 1: Register
        register_response = client.post('/api/auth/register/', {
            'username': username,
            'email': email,
            'password': password,
            'password_confirm': password,
        }, format='json')
        
        # Registration should succeed
        assert register_response.status_code == 201, \
            f"Registration failed: {register_response.data}"
        assert 'tokens' in register_response.data
        assert 'access' in register_response.data['tokens']
        assert 'refresh' in register_response.data['tokens']
        
        # Step 2: Login with same credentials
        login_response = client.post('/api/auth/login/', {
            'username': username,
            'password': password,
        }, format='json')
        
        # Login should succeed
        assert login_response.status_code == 200, \
            f"Login failed: {login_response.data}"
        assert 'tokens' in login_response.data
        assert 'access' in login_response.data['tokens']
        assert 'refresh' in login_response.data['tokens']
        
        # Verify tokens are valid (non-empty strings)
        assert login_response.data['tokens']['access']
        assert login_response.data['tokens']['refresh']
        
        # Cleanup
        User.objects.filter(username=username).delete()


@pytest.mark.django_db(transaction=True)
class TestInvalidRegistrationDataRejection:
    """
    Property 2: Invalid Registration Data Rejection
    
    For any invalid registration data (empty username, invalid email format,
    weak password), the registration request should be rejected with
    appropriate error messages.
    
    Validates: Requirements 1.2
    """

    @settings(max_examples=100, deadline=None)
    @given(
        username=st.text(max_size=2).filter(lambda x: len(x.strip()) < 3)
    )
    def test_empty_or_short_username_rejected(self, username):
        """
        Feature: url-shortener, Property 2: 无效注册数据拒绝
        Validates: Requirements 1.2
        
        For any empty or too short username (less than 3 characters),
        registration should be rejected.
        """
        client = APIClient()
        
        response = client.post('/api/auth/register/', {
            'username': username,
            'email': 'valid@example.com',
            'password': 'ValidPass123!',
            'password_confirm': 'ValidPass123!',
        }, format='json')
        
        # Registration should fail with 400
        assert response.status_code == 400, \
            f"Expected 400 for short username '{username}', got {response.status_code}"
        assert 'error' in response.data

    @settings(max_examples=100, deadline=None)
    @given(
        invalid_email=st.one_of(
            # Missing @ symbol
            st.text(alphabet=string.ascii_letters + string.digits, min_size=5, max_size=20)
                .filter(lambda x: '@' not in x and x.strip()),
            # Missing domain
            st.builds(lambda x: f"{x}@", st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10)
                .filter(lambda x: x.strip())),
            # Missing local part
            st.builds(lambda x: f"@{x}.com", st.text(alphabet=string.ascii_lowercase, min_size=3, max_size=10)
                .filter(lambda x: x.strip())),
            # Just whitespace or empty
            st.text(alphabet=' \t\n', max_size=5),
        )
    )
    def test_invalid_email_format_rejected(self, invalid_email):
        """
        Feature: url-shortener, Property 2: 无效注册数据拒绝
        Validates: Requirements 1.2
        
        For any invalid email format, registration should be rejected.
        """
        # Skip if email accidentally becomes valid
        assume('@' not in invalid_email or 
               not invalid_email.split('@')[0].strip() or 
               '.' not in invalid_email.split('@')[-1] if '@' in invalid_email else True)
        
        client = APIClient()
        
        response = client.post('/api/auth/register/', {
            'username': 'validuser123',
            'email': invalid_email,
            'password': 'ValidPass123!',
            'password_confirm': 'ValidPass123!',
        }, format='json')
        
        # Registration should fail with 400
        assert response.status_code == 400, \
            f"Expected 400 for invalid email '{invalid_email}', got {response.status_code}"
        assert 'error' in response.data

    @settings(max_examples=100, deadline=None)
    @given(
        weak_password=st.one_of(
            # Too short (less than 8 characters)
            st.text(alphabet=string.ascii_letters + string.digits, min_size=1, max_size=7),
            # Only letters (no digits)
            st.text(alphabet=string.ascii_letters, min_size=8, max_size=20)
                .filter(lambda x: x.isalpha()),
            # Only digits (no letters)
            st.text(alphabet=string.digits, min_size=8, max_size=20)
                .filter(lambda x: x.isdigit()),
            # Common weak passwords
            st.sampled_from(['password', '12345678', 'qwerty12', 'abcdefgh']),
        )
    )
    def test_weak_password_rejected(self, weak_password):
        """
        Feature: url-shortener, Property 2: 无效注册数据拒绝
        Validates: Requirements 1.2
        
        For any weak password (too short, only letters, only digits, or common),
        registration should be rejected.
        """
        client = APIClient()
        
        # Generate unique username/email to avoid conflicts
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        
        response = client.post('/api/auth/register/', {
            'username': f'user{unique_id}',
            'email': f'test{unique_id}@example.com',
            'password': weak_password,
            'password_confirm': weak_password,
        }, format='json')
        
        # Registration should fail with 400
        assert response.status_code == 400, \
            f"Expected 400 for weak password '{weak_password}', got {response.status_code}"
        assert 'error' in response.data

    @settings(max_examples=100, deadline=None)
    @given(
        password1=valid_password_strategy(),
        password2=valid_password_strategy()
    )
    def test_password_mismatch_rejected(self, password1, password2):
        """
        Feature: url-shortener, Property 2: 无效注册数据拒绝
        Validates: Requirements 1.2
        
        For any two different passwords, registration should be rejected
        when password and password_confirm don't match.
        """
        # Ensure passwords are different
        assume(password1 != password2)
        
        client = APIClient()
        
        # Generate unique username/email to avoid conflicts
        import uuid
        unique_id = str(uuid.uuid4())[:8]
        
        response = client.post('/api/auth/register/', {
            'username': f'user{unique_id}',
            'email': f'test{unique_id}@example.com',
            'password': password1,
            'password_confirm': password2,
        }, format='json')
        
        # Registration should fail with 400
        assert response.status_code == 400, \
            f"Expected 400 for mismatched passwords, got {response.status_code}"
        assert 'error' in response.data


@pytest.mark.django_db(transaction=True)
class TestWrongCredentialsRejection:
    """
    Property 3: Wrong Credentials Rejection
    
    For any registered user and wrong password combination,
    the login request should be rejected.
    
    Validates: Requirements 1.4
    """

    @settings(max_examples=100, deadline=None)
    @given(
        username=valid_username_strategy(),
        email=valid_email_strategy(),
        correct_password=valid_password_strategy(),
        wrong_password=valid_password_strategy()
    )
    def test_wrong_password_rejected(self, username, email, correct_password, wrong_password):
        """
        Feature: url-shortener, Property 3: 错误凭证拒绝
        Validates: Requirements 1.4
        
        For any registered user and wrong password,
        login should be rejected with 401 status.
        """
        # Ensure passwords are different
        assume(correct_password != wrong_password)
        # Ensure unique test data
        assume(not User.objects.filter(username=username).exists())
        assume(not User.objects.filter(email=email).exists())
        
        client = APIClient()
        
        # Step 1: Register a user with the correct password
        register_response = client.post('/api/auth/register/', {
            'username': username,
            'email': email,
            'password': correct_password,
            'password_confirm': correct_password,
        }, format='json')
        
        # Registration should succeed
        assert register_response.status_code == 201, \
            f"Registration failed: {register_response.data}"
        
        # Step 2: Try to login with wrong password
        login_response = client.post('/api/auth/login/', {
            'username': username,
            'password': wrong_password,
        }, format='json')
        
        # Login should fail with 401
        assert login_response.status_code == 401, \
            f"Expected 401 for wrong password, got {login_response.status_code}"
        assert 'error' in login_response.data
        
        # Cleanup
        User.objects.filter(username=username).delete()

    @settings(max_examples=100, deadline=None)
    @given(
        nonexistent_username=valid_username_strategy(),
        password=valid_password_strategy()
    )
    def test_nonexistent_user_rejected(self, nonexistent_username, password):
        """
        Feature: url-shortener, Property 3: 错误凭证拒绝
        Validates: Requirements 1.4
        
        For any non-existent username, login should be rejected with 401 status.
        """
        # Ensure user doesn't exist
        assume(not User.objects.filter(username=nonexistent_username).exists())
        
        client = APIClient()
        
        # Try to login with non-existent user
        login_response = client.post('/api/auth/login/', {
            'username': nonexistent_username,
            'password': password,
        }, format='json')
        
        # Login should fail with 401
        assert login_response.status_code == 401, \
            f"Expected 401 for non-existent user, got {login_response.status_code}"
        assert 'error' in login_response.data
