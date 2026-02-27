from django.urls import path
from .redirect_views import redirect_to_original

urlpatterns = [
    path('<str:short_code>', redirect_to_original, name='redirect'),
]
