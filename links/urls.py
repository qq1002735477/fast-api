from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import LinkViewSet, GroupViewSet, TagViewSet

router = DefaultRouter()
router.register(r'', LinkViewSet, basename='link')

# Groups router
groups_router = DefaultRouter()
groups_router.register(r'', GroupViewSet, basename='group')

# Tags router
tags_router = DefaultRouter()
tags_router.register(r'', TagViewSet, basename='tag')

urlpatterns = [
    path('', include(router.urls)),
]

# These will be included in the main urls.py
groups_urlpatterns = [
    path('', include(groups_router.urls)),
]

tags_urlpatterns = [
    path('', include(tags_router.urls)),
]
