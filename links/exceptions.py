"""
Custom exception handlers for the links app.

Provides custom exception handling for rate limiting and other errors.
"""
from rest_framework.views import exception_handler
from rest_framework.exceptions import Throttled
from rest_framework.response import Response
from rest_framework import status


def custom_exception_handler(exc, context):
    """
    Custom exception handler that formats rate limit errors properly.
    
    Args:
        exc: The exception that was raised.
        context: Context dict containing view, request, etc.
    
    Returns:
        Response object with formatted error.
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)
    
    if response is not None:
        # Handle throttled (rate limited) exceptions
        if isinstance(exc, Throttled):
            request = context.get('request')
            
            # Get rate limit info from request if available
            ratelimit_info = getattr(request, '_ratelimit_info', None)
            
            # Build custom error response
            error_data = {
                'error': {
                    'code': 'RATE_LIMIT_EXCEEDED',
                    'message': '请求频率超限，请稍后重试',
                    'details': {
                        'retry_after': exc.wait or 60,
                    }
                }
            }
            
            if ratelimit_info:
                error_data['error']['details']['limit'] = ratelimit_info['limit']
                error_data['error']['details']['reset'] = ratelimit_info['reset']
            
            response = Response(error_data, status=status.HTTP_429_TOO_MANY_REQUESTS)
            
            # Add rate limit headers
            if ratelimit_info:
                response['X-RateLimit-Limit'] = str(ratelimit_info['limit'])
                response['X-RateLimit-Remaining'] = '0'
                response['X-RateLimit-Reset'] = str(ratelimit_info['reset'])
                response['Retry-After'] = str(ratelimit_info['reset'])
            else:
                response['Retry-After'] = str(int(exc.wait or 60))
    
    return response
