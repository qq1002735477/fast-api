"""
Django settings for urlshortener project.
"""
import os
from pathlib import Path
from datetime import timedelta
from decouple import config

# Use PyMySQL as MySQLdb replacement
import pymysql
pymysql.install_as_MySQLdb()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-dev-key-change-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=lambda v: [s.strip() for s in v.split(',')])

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Third party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'corsheaders',
    'drf_spectacular',
    # Local apps
    'users',
    'links',
    'stats',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'links.middleware.RateLimitHeadersMiddleware',
]

ROOT_URLCONF = 'urlshortener.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'urlshortener.wsgi.application'

# Database - MySQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME', default='urlshortener'),
        'USER': config('DB_USER', default='root'),
        'PASSWORD': config('DB_PASSWORD', default='password'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='3306'),
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

# Redis Cache
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': config('REDIS_URL', default='redis://localhost:6379/0'),
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
        }
    }
}

# Celery Configuration
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/1')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/1')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'users.User'

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_THROTTLE_CLASSES': [
        'links.throttling.SlidingWindowThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '20/minute',
        'user': '100/minute',
    },
    'EXCEPTION_HANDLER': 'links.exceptions.custom_exception_handler',
}

# JWT Configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    'ALGORITHM': 'HS256',
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
}

# CORS Configuration
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:3000,http://127.0.0.1:3000',
    cast=lambda v: [s.strip() for s in v.split(',')]
)
CORS_ALLOW_CREDENTIALS = True
# 允许本地文件和所有 localhost 端口访问（开发环境）
CORS_ALLOW_ALL_ORIGINS = DEBUG

# Additional CORS security settings
CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# Expose rate limit headers to frontend
CORS_EXPOSE_HEADERS = [
    'X-RateLimit-Limit',
    'X-RateLimit-Remaining',
    'X-RateLimit-Reset',
    'Retry-After',
]

# Preflight cache duration (in seconds)
CORS_PREFLIGHT_MAX_AGE = 86400  # 24 hours

# DRF Spectacular Configuration
SPECTACULAR_SETTINGS = {
    'TITLE': '短链接服务 API',
    'DESCRIPTION': '''
## 概述

短链接服务是一个功能完整的 URL 缩短服务 API，提供以下核心功能：

- **用户认证**: 基于 JWT 的用户注册、登录和令牌管理
- **短链接管理**: 创建、查询、更新和删除短链接
- **访问统计**: 查看链接点击量、独立访客和时间维度统计
- **批量操作**: 批量创建和删除短链接
- **分组与标签**: 使用分组和标签组织短链接
- **数据导出**: 导出链接数据为 CSV 文件

## 认证方式

本 API 使用 JWT (JSON Web Token) 进行认证。

### 获取令牌

1. 调用 `/api/auth/register/` 注册新用户，或调用 `/api/auth/login/` 登录
2. 成功后会返回 `access` 和 `refresh` 令牌

### 使用令牌

在请求头中添加：
```
Authorization: Bearer <access_token>
```

### 刷新令牌

当 access token 过期时，使用 refresh token 调用 `/api/auth/token/refresh/` 获取新的 access token。

## 限流策略

- **已认证用户**: 100 次请求/分钟
- **匿名用户**: 20 次请求/分钟

超过限制时返回 HTTP 429，响应头包含：
- `X-RateLimit-Limit`: 限制次数
- `X-RateLimit-Remaining`: 剩余次数
- `X-RateLimit-Reset`: 重置时间戳
- `Retry-After`: 重试等待秒数

## 错误响应格式

```json
{
    "error": {
        "code": "ERROR_CODE",
        "message": "错误描述",
        "details": [...]
    }
}
```

常见错误码：
- `VALIDATION_ERROR`: 请求参数验证失败
- `AUTHENTICATION_ERROR`: 认证失败
- `PERMISSION_DENIED`: 无权限访问
- `LINK_NOT_FOUND`: 链接不存在
- `LINK_EXPIRED`: 链接已过期
- `RATE_LIMIT_EXCEEDED`: 请求频率超限
''',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'CONTACT': {
        'name': 'API Support',
        'email': 'support@example.com',
    },
    'LICENSE': {
        'name': 'MIT License',
    },
    'TAGS': [
        {'name': '认证', 'description': '用户注册、登录和令牌管理'},
        {'name': '短链接', 'description': '短链接的创建、查询、更新和删除'},
        {'name': '重定向', 'description': '短链接重定向服务'},
        {'name': '统计', 'description': '访问统计和数据分析'},
        {'name': '分组', 'description': '链接分组管理'},
        {'name': '标签', 'description': '链接标签管理'},
        {'name': '批量操作', 'description': '批量创建和删除短链接'},
        {'name': '数据导出', 'description': '导出链接数据'},
    ],
    'COMPONENT_SPLIT_REQUEST': True,
    'SCHEMA_PATH_PREFIX': r'/api/',
    'SECURITY': [
        {'Bearer': []},
    ],
    'SWAGGER_UI_SETTINGS': {
        'deepLinking': True,
        'persistAuthorization': True,
        'displayOperationId': False,
        'filter': True,
    },
    'ENUM_NAME_OVERRIDES': {
        'ExportStatusEnum': 'stats.models.ExportTask.STATUS_CHOICES',
    },
}

# Short Code Configuration
SHORT_CODE_LENGTH = 6
SHORT_CODE_MIN_LENGTH = 4
SHORT_CODE_MAX_LENGTH = 10

# Link Cache TTL (seconds)
LINK_CACHE_TTL = 3600  # 1 hour

# Rate Limit Configuration
RATE_LIMIT_AUTHENTICATED = 100  # requests per minute for authenticated users
RATE_LIMIT_ANONYMOUS = 20  # requests per minute for anonymous users
RATE_LIMIT_WINDOW = 60  # window size in seconds

# Export Configuration
EXPORT_FILE_PATH = BASE_DIR / 'exports'
