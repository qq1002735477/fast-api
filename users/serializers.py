"""
User serializers for authentication.
"""
import re
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


def validate_password_strength(password):
    """
    Custom password validator that requires:
    - At least 8 characters
    - At least one letter
    - At least one digit
    """
    if len(password) < 8:
        raise serializers.ValidationError("密码至少需要8个字符")
    if not re.search(r'[a-zA-Z]', password):
        raise serializers.ValidationError("密码必须包含至少一个字母")
    if not re.search(r'\d', password):
        raise serializers.ValidationError("密码必须包含至少一个数字")
    return password


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration."""
    password = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=True,
        style={'input_type': 'password'}
    )

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'password_confirm')

    def validate_email(self, value):
        """Validate email is unique."""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("该邮箱已被注册")
        return value

    def validate_username(self, value):
        """Validate username."""
        if not value or not value.strip():
            raise serializers.ValidationError("用户名不能为空")
        if len(value) < 3:
            raise serializers.ValidationError("用户名至少需要3个字符")
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("该用户名已被使用")
        return value

    def validate(self, attrs):
        """Validate passwords match and password strength."""
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                'password_confirm': '两次输入的密码不一致'
            })
        # Validate password strength
        validate_password_strength(attrs['password'])
        # Also run Django's built-in validators
        try:
            validate_password(attrs['password'])
        except DjangoValidationError as e:
            raise serializers.ValidationError({
                'password': list(e.messages)
            })
        return attrs

    def create(self, validated_data):
        """Create user with hashed password."""
        validated_data.pop('password_confirm')
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        return user


class UserLoginSerializer(TokenObtainPairSerializer):
    """Serializer for user login with JWT tokens."""
    
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add custom claims
        token['username'] = user.username
        token['email'] = user.email
        return token

    def validate(self, attrs):
        """Validate credentials and return tokens."""
        try:
            data = super().validate(attrs)
        except Exception:
            raise serializers.ValidationError({
                'detail': '用户名或密码错误'
            })
        
        # Add user info to response
        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'email': self.user.email,
        }
        return data


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user profile."""
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')
