"""
Pytest configuration and fixtures for testing.
"""
import pytest


# Configure Celery to run tasks synchronously in tests
@pytest.fixture(scope='session', autouse=True)
def celery_eager_mode():
    """Configure Celery to run tasks synchronously."""
    try:
        from urlshortener.celery import app
        app.conf.task_always_eager = True
        app.conf.task_eager_propagates = True
    except ImportError:
        pass


@pytest.fixture
def api_client():
    """Return an API client for testing."""
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def create_user(db):
    """Factory fixture to create users."""
    def _create_user(username='testuser', email='test@example.com', password='testpass123'):
        from users.models import User
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        return user
    return _create_user


@pytest.fixture
def authenticated_client(api_client, create_user):
    """Return an authenticated API client."""
    user = create_user()
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken.for_user(user)
    api_client.credentials(HTTP_AUTHORIZATION=f'Bearer {refresh.access_token}')
    api_client.user = user
    return api_client
