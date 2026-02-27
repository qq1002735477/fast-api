"""
User views for authentication.
"""
from rest_framework import status, generics
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

from .serializers import (
    UserRegistrationSerializer,
    UserLoginSerializer,
    UserSerializer,
)


class UserRegistrationView(generics.CreateAPIView):
    """
    User registration endpoint.
    
    Creates a new user account with username, email, and password.
    Returns user info and JWT tokens on success.
    """
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['认证'],
        summary="用户注册",
        description="""
创建新用户账户。

### 密码要求
- 至少 8 个字符
- 必须包含至少一个字母
- 必须包含至少一个数字

### 成功响应
注册成功后会自动返回 JWT 令牌，可直接用于后续 API 调用。
        """,
        request=UserRegistrationSerializer,
        responses={
            201: OpenApiResponse(
                description="注册成功",
                examples=[
                    OpenApiExample(
                        '注册成功',
                        value={
                            'message': '注册成功',
                            'user': {
                                'id': 1,
                                'username': 'testuser',
                                'email': 'test@example.com'
                            },
                            'tokens': {
                                'refresh': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                                'access': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'
                            }
                        }
                    )
                ]
            ),
            400: OpenApiResponse(
                description="验证失败",
                examples=[
                    OpenApiExample(
                        '邮箱已存在',
                        value={
                            'error': {
                                'code': 'VALIDATION_ERROR',
                                'message': '注册信息验证失败',
                                'details': {'email': ['该邮箱已被注册']}
                            }
                        }
                    ),
                    OpenApiExample(
                        '密码不符合要求',
                        value={
                            'error': {
                                'code': 'VALIDATION_ERROR',
                                'message': '注册信息验证失败',
                                'details': {'password': ['密码至少需要8个字符']}
                            }
                        }
                    )
                ]
            ),
        },
        examples=[
            OpenApiExample(
                '注册请求示例',
                value={
                    'username': 'testuser',
                    'email': 'test@example.com',
                    'password': 'SecurePass123',
                    'password_confirm': 'SecurePass123'
                },
                request_only=True
            )
        ]
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            # Generate tokens for the new user
            refresh = RefreshToken.for_user(user)
            return Response({
                'message': '注册成功',
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                },
                'tokens': {
                    'refresh': str(refresh),
                    'access': str(refresh.access_token),
                }
            }, status=status.HTTP_201_CREATED)
        return Response({
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': '注册信息验证失败',
                'details': serializer.errors
            }
        }, status=status.HTTP_400_BAD_REQUEST)


class UserLoginView(TokenObtainPairView):
    """
    User login endpoint.
    
    Authenticates user with username and password.
    Returns JWT access and refresh tokens on success.
    """
    serializer_class = UserLoginSerializer
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['认证'],
        summary="用户登录",
        description="""
使用用户名和密码登录，返回 JWT 令牌。

### 令牌有效期
- Access Token: 30 分钟
- Refresh Token: 7 天

### 使用方式
在后续请求的 Header 中添加：
```
Authorization: Bearer <access_token>
```
        """,
        responses={
            200: OpenApiResponse(
                description="登录成功",
                examples=[
                    OpenApiExample(
                        '登录成功',
                        value={
                            'message': '登录成功',
                            'user': {
                                'id': 1,
                                'username': 'testuser',
                                'email': 'test@example.com'
                            },
                            'tokens': {
                                'refresh': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                                'access': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'
                            }
                        }
                    )
                ]
            ),
            401: OpenApiResponse(
                description="认证失败",
                examples=[
                    OpenApiExample(
                        '密码错误',
                        value={
                            'error': {
                                'code': 'AUTHENTICATION_ERROR',
                                'message': '用户名或密码错误'
                            }
                        }
                    )
                ]
            ),
        },
        examples=[
            OpenApiExample(
                '登录请求示例',
                value={
                    'username': 'testuser',
                    'password': 'SecurePass123'
                },
                request_only=True
            )
        ]
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            return Response({
                'error': {
                    'code': 'AUTHENTICATION_ERROR',
                    'message': '用户名或密码错误',
                }
            }, status=status.HTTP_401_UNAUTHORIZED)
        
        return Response({
            'message': '登录成功',
            'user': serializer.validated_data.get('user'),
            'tokens': {
                'refresh': serializer.validated_data.get('refresh'),
                'access': serializer.validated_data.get('access'),
            }
        }, status=status.HTTP_200_OK)


class CustomTokenRefreshView(TokenRefreshView):
    """
    Token refresh endpoint.
    
    Refreshes an access token using a valid refresh token.
    """
    permission_classes = [AllowAny]

    @extend_schema(
        tags=['认证'],
        summary="刷新令牌",
        description="""
使用刷新令牌获取新的访问令牌。

当 access token 过期时，使用此接口获取新的 access token，无需重新登录。

### 注意事项
- Refresh token 使用后会轮换，返回新的 refresh token
- 旧的 refresh token 将失效
        """,
        responses={
            200: OpenApiResponse(
                description="刷新成功",
                examples=[
                    OpenApiExample(
                        '刷新成功',
                        value={
                            'message': '令牌刷新成功',
                            'tokens': {
                                'access': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...',
                                'refresh': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'
                            }
                        }
                    )
                ]
            ),
            401: OpenApiResponse(
                description="刷新令牌无效或已过期",
                examples=[
                    OpenApiExample(
                        '令牌无效',
                        value={
                            'error': {
                                'code': 'TOKEN_ERROR',
                                'message': '刷新令牌无效或已过期'
                            }
                        }
                    )
                ]
            ),
        },
        examples=[
            OpenApiExample(
                '刷新请求示例',
                value={
                    'refresh': 'eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...'
                },
                request_only=True
            )
        ]
    )
    def post(self, request, *args, **kwargs):
        try:
            response = super().post(request, *args, **kwargs)
            return Response({
                'message': '令牌刷新成功',
                'tokens': {
                    'access': response.data.get('access'),
                    'refresh': response.data.get('refresh'),
                }
            }, status=status.HTTP_200_OK)
        except TokenError:
            return Response({
                'error': {
                    'code': 'TOKEN_ERROR',
                    'message': '刷新令牌无效或已过期',
                }
            }, status=status.HTTP_401_UNAUTHORIZED)


class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    User profile endpoint.
    
    Get or update the authenticated user's profile.
    """
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['认证'],
        summary="获取用户信息",
        description="获取当前登录用户的个人信息。",
        responses={
            200: UserSerializer,
        }
    )
    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @extend_schema(
        tags=['认证'],
        summary="更新用户信息",
        description="更新当前登录用户的个人信息。",
        responses={
            200: UserSerializer,
            400: OpenApiResponse(description="验证失败"),
        }
    )
    def put(self, request, *args, **kwargs):
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response({
            'error': {
                'code': 'VALIDATION_ERROR',
                'message': '更新信息验证失败',
                'details': serializer.errors
            }
        }, status=status.HTTP_400_BAD_REQUEST)

    def get_object(self):
        return self.request.user
