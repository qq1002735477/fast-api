"""
URL configuration for urlshortener project.
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from links.urls import groups_urlpatterns, tags_urlpatterns

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # API endpoints
    path('api/auth/', include('users.urls')),
    path('api/links/', include('links.urls')),
    path('api/groups/', include(groups_urlpatterns)),
    path('api/tags/', include(tags_urlpatterns)),
    path('api/', include('stats.urls')),
    
    # Redirect endpoint
    path('r/', include('links.redirect_urls')),
    
    # API Documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
