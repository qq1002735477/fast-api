"""
Serializers for the links app.
"""
from rest_framework import serializers
from django.utils import timezone

from .models import Link, AccessLog, Group, Tag
from .services import short_code_generator
from .security import url_security_service


class TagSerializer(serializers.ModelSerializer):
    """Serializer for Tag model."""
    
    class Meta:
        model = Tag
        fields = ['id', 'name']
        read_only_fields = ['id']
    
    def validate_name(self, value):
        """Validate and sanitize tag name."""
        if not value:
            return value
        
        # Check for XSS/SQL injection
        validation_result = url_security_service.validate_input(value)
        if not validation_result['is_valid']:
            raise serializers.ValidationError(
                'Tag name contains invalid characters'
            )
        
        return value


class GroupSerializer(serializers.ModelSerializer):
    """Serializer for Group model."""
    
    class Meta:
        model = Group
        fields = ['id', 'name', 'description', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def validate_name(self, value):
        """Validate and sanitize group name."""
        if not value:
            return value
        
        # Check for XSS/SQL injection
        validation_result = url_security_service.validate_input(value)
        if not validation_result['is_valid']:
            raise serializers.ValidationError(
                'Group name contains invalid characters'
            )
        
        return value
    
    def validate_description(self, value):
        """Validate and sanitize group description."""
        if not value:
            return value
        
        # Check for XSS/SQL injection
        validation_result = url_security_service.validate_input(value)
        if not validation_result['is_valid']:
            raise serializers.ValidationError(
                'Group description contains invalid characters'
            )
        
        return value


class LinkSerializer(serializers.ModelSerializer):
    """Serializer for Link model - read operations."""
    tags = TagSerializer(many=True, read_only=True)
    group = GroupSerializer(read_only=True)
    
    class Meta:
        model = Link
        fields = [
            'id', 'short_code', 'original_url', 'group', 'tags',
            'created_at', 'updated_at', 'expires_at', 'click_count', 'is_active'
        ]
        read_only_fields = [
            'id', 'short_code', 'created_at', 'updated_at', 'click_count'
        ]


class LinkCreateSerializer(serializers.Serializer):
    """Serializer for creating short links."""
    original_url = serializers.URLField(
        max_length=2048,
        help_text='The original URL to shorten'
    )
    custom_code = serializers.CharField(
        max_length=10,
        min_length=4,
        required=False,
        allow_blank=True,
        help_text='Optional custom short code (4-10 Base62 characters)'
    )
    expires_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text='Optional expiration datetime'
    )
    group_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text='Optional group ID'
    )
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        help_text='Optional list of tag IDs'
    )
    
    def validate_original_url(self, value):
        """Validate URL is not in malicious domain blacklist."""
        safety_check = url_security_service.check_url_safety(value)
        
        if not safety_check['is_safe']:
            raise serializers.ValidationError(
                f"URL rejected: {safety_check['reason']}"
            )
        
        return value
    
    def validate_custom_code(self, value):
        """Validate custom short code format and availability."""
        if not value:
            return value
        
        # Check for XSS/SQL injection patterns
        validation_result = url_security_service.validate_input(value)
        if not validation_result['is_valid']:
            raise serializers.ValidationError(
                'Custom code contains invalid characters'
            )
        
        # Validate format
        if not short_code_generator.validate(value):
            raise serializers.ValidationError(
                'Custom code must be 4-10 characters and contain only '
                'alphanumeric characters (a-z, A-Z, 0-9)'
            )
        
        # Check availability
        if not short_code_generator.is_available(value):
            raise serializers.ValidationError(
                'This custom code is already in use'
            )
        
        return value
    
    def validate_expires_at(self, value):
        """Validate expiration time is in the future."""
        if value and value <= timezone.now():
            raise serializers.ValidationError(
                'Expiration time must be in the future'
            )
        return value
    
    def validate_group_id(self, value):
        """Validate group belongs to the user."""
        if value is None:
            return value
        
        user = self.context.get('request').user
        if not Group.objects.filter(id=value, user=user).exists():
            raise serializers.ValidationError(
                'Group not found or does not belong to you'
            )
        return value
    
    def validate_tag_ids(self, value):
        """Validate tags belong to the user."""
        if not value:
            return value
        
        user = self.context.get('request').user
        existing_tags = Tag.objects.filter(id__in=value, user=user)
        if existing_tags.count() != len(value):
            raise serializers.ValidationError(
                'One or more tags not found or do not belong to you'
            )
        return value
    
    def create(self, validated_data):
        """Create a new short link or return existing one for same URL."""
        user = self.context.get('request').user
        original_url = validated_data['original_url']
        custom_code = validated_data.get('custom_code')
        expires_at = validated_data.get('expires_at')
        group_id = validated_data.get('group_id')
        tag_ids = validated_data.get('tag_ids', [])
        
        # Check if user already has a link for this URL (idempotency)
        existing_link = Link.objects.filter(
            user=user,
            original_url=original_url
        ).first()
        
        if existing_link:
            # Return existing link instead of creating a new one
            return existing_link
        
        # Generate or use custom short code
        if custom_code:
            short_code = custom_code
        else:
            short_code = short_code_generator.generate_unique()
        
        # Create the link
        link = Link.objects.create(
            short_code=short_code,
            original_url=original_url,
            user=user,
            group_id=group_id,
            expires_at=expires_at
        )
        
        # Add tags if provided
        if tag_ids:
            link.tags.set(tag_ids)
        
        return link


class LinkUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating short links."""
    expires_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text='Expiration datetime (set to null to remove expiration)'
    )
    group_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text='Group ID'
    )
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text='List of tag IDs'
    )
    
    class Meta:
        model = Link
        fields = ['original_url', 'expires_at', 'is_active', 'group_id', 'tag_ids']
        extra_kwargs = {
            'original_url': {'required': False},
        }
    
    def validate_expires_at(self, value):
        """Validate expiration time is in the future if set."""
        # Allow null to remove expiration
        if value is None:
            return value
        if value <= timezone.now():
            raise serializers.ValidationError(
                'Expiration time must be in the future'
            )
        return value
    
    def validate_group_id(self, value):
        """Validate group belongs to the user."""
        if value is None:
            return value
        
        user = self.context.get('request').user
        if not Group.objects.filter(id=value, user=user).exists():
            raise serializers.ValidationError(
                'Group not found or does not belong to you'
            )
        return value
    
    def validate_tag_ids(self, value):
        """Validate tags belong to the user."""
        if not value:
            return value
        
        user = self.context.get('request').user
        existing_tags = Tag.objects.filter(id__in=value, user=user)
        if existing_tags.count() != len(value):
            raise serializers.ValidationError(
                'One or more tags not found or do not belong to you'
            )
        return value
    
    def update(self, instance, validated_data):
        """Update the link and invalidate cache."""
        tag_ids = validated_data.pop('tag_ids', None)
        group_id = validated_data.pop('group_id', None)
        
        # Handle expires_at explicitly to allow setting to None
        if 'expires_at' in validated_data:
            instance.expires_at = validated_data.pop('expires_at')
        
        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Update group if provided (including setting to None)
        if 'group_id' in self.initial_data:
            instance.group_id = group_id
        
        instance.save()
        
        # Update tags if provided
        if tag_ids is not None:
            instance.tags.set(tag_ids)
        
        return instance


class AccessLogSerializer(serializers.ModelSerializer):
    """Serializer for AccessLog model."""
    
    class Meta:
        model = AccessLog
        fields = ['id', 'ip_address', 'user_agent', 'referer', 'accessed_at']
        read_only_fields = ['id', 'accessed_at']


class BatchLinkItemSerializer(serializers.Serializer):
    """Serializer for a single item in batch link creation."""
    original_url = serializers.CharField(
        max_length=2048,
        help_text='The original URL to shorten'
    )
    custom_code = serializers.CharField(
        max_length=10,
        min_length=4,
        required=False,
        allow_blank=True,
        help_text='Optional custom short code (4-10 Base62 characters)'
    )
    expires_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text='Optional expiration datetime'
    )
    group_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text='Optional group ID'
    )
    tag_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        default=list,
        help_text='Optional list of tag IDs'
    )


class BatchCreateSerializer(serializers.Serializer):
    """Serializer for batch link creation request."""
    links = serializers.ListField(
        child=BatchLinkItemSerializer(),
        min_length=1,
        max_length=50,
        help_text='List of links to create (max 50)'
    )
    
    def validate_links(self, value):
        """Validate the list of links."""
        if len(value) > 50:
            raise serializers.ValidationError(
                'Maximum 50 links allowed per batch request'
            )
        return value


class BatchCreateResultSerializer(serializers.Serializer):
    """Serializer for a single result in batch creation response."""
    index = serializers.IntegerField(help_text='Index of the item in the request')
    success = serializers.BooleanField(help_text='Whether the creation succeeded')
    short_code = serializers.CharField(required=False, allow_null=True)
    original_url = serializers.CharField(required=False, allow_null=True)
    error = serializers.CharField(required=False, allow_null=True)


class BatchCreateResponseSerializer(serializers.Serializer):
    """Serializer for batch creation response."""
    total = serializers.IntegerField(help_text='Total number of items in request')
    successful = serializers.IntegerField(help_text='Number of successfully created links')
    failed = serializers.IntegerField(help_text='Number of failed creations')
    results = BatchCreateResultSerializer(many=True)
    async_task_id = serializers.CharField(
        required=False, 
        allow_null=True,
        help_text='Task ID for async processing (when > 10 items)'
    )


class BatchDeleteSerializer(serializers.Serializer):
    """Serializer for batch link deletion request."""
    short_codes = serializers.ListField(
        child=serializers.CharField(max_length=10),
        min_length=1,
        max_length=100,
        help_text='List of short codes to delete (max 100)'
    )
    
    def validate_short_codes(self, value):
        """Validate the list of short codes."""
        if len(value) > 100:
            raise serializers.ValidationError(
                'Maximum 100 short codes allowed per batch delete request'
            )
        return value


class BatchDeleteResultSerializer(serializers.Serializer):
    """Serializer for a single result in batch deletion response."""
    short_code = serializers.CharField()
    success = serializers.BooleanField()
    error = serializers.CharField(required=False, allow_null=True)


class BatchDeleteResponseSerializer(serializers.Serializer):
    """Serializer for batch deletion response."""
    total = serializers.IntegerField(help_text='Total number of items in request')
    successful = serializers.IntegerField(help_text='Number of successfully deleted links')
    failed = serializers.IntegerField(help_text='Number of failed deletions')
    results = BatchDeleteResultSerializer(many=True)
