"""
Views for the links app.
"""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from django.http import Http404
from drf_spectacular.utils import (
    extend_schema, extend_schema_view, OpenApiResponse, OpenApiExample,
    OpenApiParameter
)

from .models import Link, Group, Tag
from .serializers import (
    LinkSerializer,
    LinkCreateSerializer,
    LinkUpdateSerializer,
    GroupSerializer,
    TagSerializer,
    BatchCreateSerializer,
    BatchDeleteSerializer,
    BatchCreateResponseSerializer,
    BatchDeleteResponseSerializer,
)
from .services import link_cache_service, short_code_generator
from .security import url_security_service


class LinkPagination(PageNumberPagination):
    """Pagination class for link list."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


@extend_schema_view(
    list=extend_schema(
        tags=['短链接'],
        summary="获取链接列表",
        description="获取当前用户的所有短链接，支持分页和筛选。",
        parameters=[
            OpenApiParameter(
                name='group_id',
                description='按分组 ID 筛选，传空字符串或 null 筛选无分组的链接',
                required=False,
                type=int
            ),
            OpenApiParameter(
                name='tag_id',
                description='按标签 ID 筛选',
                required=False,
                type=int
            ),
            OpenApiParameter(
                name='page',
                description='页码',
                required=False,
                type=int
            ),
            OpenApiParameter(
                name='page_size',
                description='每页数量（最大 100）',
                required=False,
                type=int
            ),
        ],
    ),
    create=extend_schema(
        tags=['短链接'],
        summary="创建短链接",
        description="""
创建新的短链接。

### 幂等性
如果用户已经为相同的原始 URL 创建过短链接，将返回已存在的短链接（HTTP 200）。

### 自定义短码
可以指定自定义短码，要求：
- 长度 4-10 个字符
- 只能包含字母和数字（Base62）
- 不能与已有短码冲突

### 过期时间
可以设置过期时间，过期后链接将返回 410 Gone。
        """,
        request=LinkCreateSerializer,
        responses={
            201: OpenApiResponse(
                response=LinkSerializer,
                description="创建成功"
            ),
            200: OpenApiResponse(
                response=LinkSerializer,
                description="返回已存在的短链接（幂等性）"
            ),
            400: OpenApiResponse(description="验证失败"),
            409: OpenApiResponse(description="自定义短码已被占用"),
        },
        examples=[
            OpenApiExample(
                '基本创建',
                value={
                    'original_url': 'https://example.com/very/long/url/path'
                },
                request_only=True
            ),
            OpenApiExample(
                '自定义短码',
                value={
                    'original_url': 'https://example.com/page',
                    'custom_code': 'mylink'
                },
                request_only=True
            ),
            OpenApiExample(
                '完整参数',
                value={
                    'original_url': 'https://example.com/page',
                    'custom_code': 'promo2024',
                    'expires_at': '2024-12-31T23:59:59Z',
                    'group_id': 1,
                    'tag_ids': [1, 2]
                },
                request_only=True
            ),
        ]
    ),
    retrieve=extend_schema(
        tags=['短链接'],
        summary="获取链接详情",
        description="获取指定短链接的详细信息。",
        responses={
            200: LinkSerializer,
            403: OpenApiResponse(description="无权限访问此链接"),
            404: OpenApiResponse(description="链接不存在"),
        }
    ),
    update=extend_schema(
        tags=['短链接'],
        summary="更新链接",
        description="""
更新短链接信息。

可更新的字段：
- `original_url`: 原始链接
- `expires_at`: 过期时间（设为 null 可移除过期时间）
- `is_active`: 是否激活
- `group_id`: 分组 ID
- `tag_ids`: 标签 ID 列表
        """,
        request=LinkUpdateSerializer,
        responses={
            200: LinkSerializer,
            400: OpenApiResponse(description="验证失败"),
            403: OpenApiResponse(description="无权限访问此链接"),
            404: OpenApiResponse(description="链接不存在"),
        }
    ),
    partial_update=extend_schema(
        tags=['短链接'],
        summary="部分更新链接",
        description="部分更新短链接信息，只需提供要更新的字段。",
        request=LinkUpdateSerializer,
        responses={
            200: LinkSerializer,
            400: OpenApiResponse(description="验证失败"),
            403: OpenApiResponse(description="无权限访问此链接"),
            404: OpenApiResponse(description="链接不存在"),
        }
    ),
    destroy=extend_schema(
        tags=['短链接'],
        summary="删除链接",
        description="删除指定的短链接，同时清除缓存。",
        responses={
            204: OpenApiResponse(description="删除成功"),
            403: OpenApiResponse(description="无权限访问此链接"),
            404: OpenApiResponse(description="链接不存在"),
        }
    ),
)
class LinkViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing short links.
    
    Provides CRUD operations for authenticated users' links.
    """
    permission_classes = [IsAuthenticated]
    pagination_class = LinkPagination
    lookup_field = 'short_code'
    lookup_url_kwarg = 'pk'
    
    def get_queryset(self):
        """Return only links belonging to the authenticated user with optional filtering."""
        queryset = Link.objects.filter(user=self.request.user).select_related(
            'group'
        ).prefetch_related('tags').order_by('-created_at')
        
        # Filter by group_id if provided
        group_id = self.request.query_params.get('group_id')
        if group_id is not None:
            if group_id == '' or group_id.lower() == 'null':
                queryset = queryset.filter(group__isnull=True)
            else:
                try:
                    queryset = queryset.filter(group_id=int(group_id))
                except (ValueError, TypeError):
                    pass
        
        # Filter by tag_id if provided
        tag_id = self.request.query_params.get('tag_id')
        if tag_id is not None:
            try:
                queryset = queryset.filter(tags__id=int(tag_id))
            except (ValueError, TypeError):
                pass
        
        return queryset
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'create':
            return LinkCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return LinkUpdateSerializer
        return LinkSerializer
    
    def get_object(self):
        """Get link by short_code."""
        short_code = self.kwargs.get('pk')
        
        try:
            link = Link.objects.get(short_code=short_code)
        except Link.DoesNotExist:
            raise Http404("Link not found")
        
        if link.user != self.request.user:
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not have permission to access this link")
        
        return link
    
    def create(self, request, *args, **kwargs):
        """Create a new short link or return existing one."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        original_url = serializer.validated_data.get('original_url')
        existing_link = Link.objects.filter(
            user=request.user,
            original_url=original_url
        ).first()
        
        link = serializer.save()
        output_serializer = LinkSerializer(link)
        
        status_code = status.HTTP_200_OK if existing_link else status.HTTP_201_CREATED
        return Response(output_serializer.data, status=status_code)
    
    def retrieve(self, request, *args, **kwargs):
        """Get link details with statistics."""
        instance = self.get_object()
        serializer = LinkSerializer(instance)
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):
        """Update an existing short link and invalidate cache."""
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        link = serializer.save()
        
        link_cache_service.delete(link.short_code)
        
        output_serializer = LinkSerializer(link)
        return Response(output_serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        """Delete a short link and invalidate cache."""
        instance = self.get_object()
        short_code = instance.short_code
        
        instance.delete()
        link_cache_service.delete(short_code)
        
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        tags=['统计'],
        summary="获取链接统计",
        description="""
获取指定短链接的访问统计信息。

### 返回数据
- 总点击量
- 独立访客数（按 IP 统计）
- 最近访问记录
- 按天分组的统计数据（可指定日期范围）
        """,
        parameters=[
            OpenApiParameter(
                name='start_date',
                description='统计开始日期（YYYY-MM-DD 格式）',
                required=False,
                type=str
            ),
            OpenApiParameter(
                name='end_date',
                description='统计结束日期（YYYY-MM-DD 格式）',
                required=False,
                type=str
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="统计数据",
                examples=[
                    OpenApiExample(
                        '统计响应',
                        value={
                            'short_code': 'abc123',
                            'original_url': 'https://example.com',
                            'click_count': 150,
                            'unique_visitors': 89,
                            'created_at': '2024-01-01T00:00:00Z',
                            'expires_at': None,
                            'recent_access_logs': [
                                {
                                    'ip_address': '192.168.1.1',
                                    'user_agent': 'Mozilla/5.0...',
                                    'accessed_at': '2024-01-15T10:30:00Z'
                                }
                            ],
                            'daily_stats': [
                                {'date': '2024-01-14', 'clicks': 25},
                                {'date': '2024-01-15', 'clicks': 30}
                            ]
                        }
                    )
                ]
            ),
            403: OpenApiResponse(description="无权限访问此链接"),
            404: OpenApiResponse(description="链接不存在"),
        }
    )
    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """Get statistics for a specific link."""
        from datetime import datetime
        from stats.services import stats_service
        
        link = self.get_object()
        basic_stats = stats_service.get_link_stats(link)
        
        stats_data = {
            'short_code': link.short_code,
            'original_url': link.original_url,
            'click_count': basic_stats['click_count'],
            'unique_visitors': basic_stats['unique_visitors'],
            'created_at': link.created_at,
            'expires_at': link.expires_at,
            'recent_access_logs': basic_stats['recent_access_logs'],
        }
        
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        
        start_date = None
        end_date = None
        
        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        
        daily_stats = stats_service.get_daily_stats(
            link,
            start_date=start_date,
            end_date=end_date
        )
        stats_data['daily_stats'] = daily_stats
        
        return Response(stats_data)
    
    @extend_schema(
        tags=['批量操作'],
        summary="批量创建短链接",
        description="""
批量创建多个短链接。

### 限制
- 每次请求最多 50 个链接
- 超过 10 个链接时异步处理

### 部分成功
支持部分成功：有效链接会被创建，无效链接返回错误信息。
        """,
        request=BatchCreateSerializer,
        responses={
            201: BatchCreateResponseSerializer,
            202: OpenApiResponse(description="已接受，异步处理中"),
            400: OpenApiResponse(description="验证失败"),
        },
    )
    @action(detail=False, methods=['post'], url_path='batch')
    def batch_create(self, request):
        """Batch create multiple short links."""
        from django.utils import timezone
        
        serializer = BatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        links_data = serializer.validated_data['links']
        user = request.user
        
        if len(links_data) > 10:
            try:
                from .tasks import batch_create_links_async
                
                async_links_data = []
                for link_data in links_data:
                    item = dict(link_data)
                    if item.get('expires_at'):
                        item['expires_at'] = item['expires_at'].isoformat()
                    async_links_data.append(item)
                
                task = batch_create_links_async.delay(user.id, async_links_data)
                
                return Response({
                    'total': len(links_data),
                    'successful': 0,
                    'failed': 0,
                    'results': [],
                    'async_task_id': task.id,
                    'message': 'Batch creation queued for async processing'
                }, status=status.HTTP_202_ACCEPTED)
            except ImportError:
                pass
        
        results = []
        successful = 0
        failed = 0
        
        for index, link_data in enumerate(links_data):
            try:
                original_url = link_data.get('original_url')
                custom_code = link_data.get('custom_code')
                expires_at = link_data.get('expires_at')
                group_id = link_data.get('group_id')
                tag_ids = link_data.get('tag_ids', [])
                
                from django.core.validators import URLValidator
                from django.core.exceptions import ValidationError as DjangoValidationError
                url_validator = URLValidator()
                try:
                    url_validator(original_url)
                except DjangoValidationError:
                    results.append({
                        'index': index,
                        'success': False,
                        'short_code': None,
                        'original_url': original_url,
                        'error': 'Invalid URL format'
                    })
                    failed += 1
                    continue
                
                safety_check = url_security_service.check_url_safety(original_url)
                if not safety_check['is_safe']:
                    results.append({
                        'index': index,
                        'success': False,
                        'short_code': None,
                        'original_url': original_url,
                        'error': f"URL rejected: {safety_check['reason']}"
                    })
                    failed += 1
                    continue
                
                existing_link = Link.objects.filter(
                    user=user,
                    original_url=original_url
                ).first()
                
                if existing_link:
                    results.append({
                        'index': index,
                        'success': True,
                        'short_code': existing_link.short_code,
                        'original_url': original_url,
                        'error': None
                    })
                    successful += 1
                    continue
                
                if custom_code:
                    if not short_code_generator.validate(custom_code):
                        results.append({
                            'index': index,
                            'success': False,
                            'short_code': None,
                            'original_url': original_url,
                            'error': 'Invalid custom code format'
                        })
                        failed += 1
                        continue
                    
                    if not short_code_generator.is_available(custom_code):
                        results.append({
                            'index': index,
                            'success': False,
                            'short_code': None,
                            'original_url': original_url,
                            'error': 'Custom code already in use'
                        })
                        failed += 1
                        continue
                    
                    short_code = custom_code
                else:
                    short_code = short_code_generator.generate_unique()
                
                if group_id:
                    if not Group.objects.filter(id=group_id, user=user).exists():
                        results.append({
                            'index': index,
                            'success': False,
                            'short_code': None,
                            'original_url': original_url,
                            'error': 'Group not found or does not belong to you'
                        })
                        failed += 1
                        continue
                
                if tag_ids:
                    existing_tags = Tag.objects.filter(id__in=tag_ids, user=user)
                    if existing_tags.count() != len(tag_ids):
                        results.append({
                            'index': index,
                            'success': False,
                            'short_code': None,
                            'original_url': original_url,
                            'error': 'One or more tags not found'
                        })
                        failed += 1
                        continue
                
                link = Link.objects.create(
                    short_code=short_code,
                    original_url=original_url,
                    user=user,
                    group_id=group_id,
                    expires_at=expires_at
                )
                
                if tag_ids:
                    link.tags.set(tag_ids)
                
                results.append({
                    'index': index,
                    'success': True,
                    'short_code': short_code,
                    'original_url': original_url,
                    'error': None
                })
                successful += 1
                
            except Exception as e:
                results.append({
                    'index': index,
                    'success': False,
                    'short_code': None,
                    'original_url': link_data.get('original_url'),
                    'error': str(e)
                })
                failed += 1
        
        return Response({
            'total': len(links_data),
            'successful': successful,
            'failed': failed,
            'results': results,
            'async_task_id': None
        }, status=status.HTTP_201_CREATED if successful > 0 else status.HTTP_400_BAD_REQUEST)
    
    @extend_schema(
        tags=['批量操作'],
        summary="批量删除短链接",
        description="""
批量删除多个短链接。

### 限制
- 每次请求最多 100 个短码
- 只能删除自己拥有的链接
        """,
        request=BatchDeleteSerializer,
        responses={
            200: BatchDeleteResponseSerializer,
            400: OpenApiResponse(description="验证失败"),
        },
    )
    @action(detail=False, methods=['post'], url_path='batch/delete')
    def batch_delete(self, request):
        """Batch delete multiple short links."""
        serializer = BatchDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        short_codes = serializer.validated_data['short_codes']
        user = request.user
        
        results = []
        successful = 0
        failed = 0
        
        for short_code in short_codes:
            try:
                link = Link.objects.filter(
                    short_code=short_code,
                    user=user
                ).first()
                
                if not link:
                    results.append({
                        'short_code': short_code,
                        'success': False,
                        'error': 'Link not found or does not belong to you'
                    })
                    failed += 1
                    continue
                
                link.delete()
                link_cache_service.delete(short_code)
                
                results.append({
                    'short_code': short_code,
                    'success': True,
                    'error': None
                })
                successful += 1
                
            except Exception as e:
                results.append({
                    'short_code': short_code,
                    'success': False,
                    'error': str(e)
                })
                failed += 1
        
        return Response({
            'total': len(short_codes),
            'successful': successful,
            'failed': failed,
            'results': results
        }, status=status.HTTP_200_OK)


@extend_schema_view(
    list=extend_schema(
        tags=['分组'],
        summary="获取分组列表",
        description="获取当前用户的所有链接分组。"
    ),
    create=extend_schema(
        tags=['分组'],
        summary="创建分组",
        description="创建新的链接分组。",
    ),
    retrieve=extend_schema(
        tags=['分组'],
        summary="获取分组详情",
        description="获取指定分组的详细信息。"
    ),
    update=extend_schema(
        tags=['分组'],
        summary="更新分组",
        description="更新分组信息。"
    ),
    partial_update=extend_schema(
        tags=['分组'],
        summary="部分更新分组",
        description="部分更新分组信息。"
    ),
    destroy=extend_schema(
        tags=['分组'],
        summary="删除分组",
        description="删除分组。删除后，该分组下的链接不会被删除，只是分组字段变为空。"
    ),
)
class GroupViewSet(viewsets.ModelViewSet):
    """ViewSet for managing link groups."""
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Return only groups belonging to the authenticated user."""
        return Group.objects.filter(user=self.request.user).order_by('-created_at')
    
    def perform_create(self, serializer):
        """Set the user when creating a group."""
        serializer.save(user=self.request.user)


@extend_schema_view(
    list=extend_schema(
        tags=['标签'],
        summary="获取标签列表",
        description="获取当前用户的所有链接标签。"
    ),
    create=extend_schema(
        tags=['标签'],
        summary="创建标签",
        description="创建新的链接标签。",
    ),
    retrieve=extend_schema(
        tags=['标签'],
        summary="获取标签详情",
        description="获取指定标签的详细信息。"
    ),
    update=extend_schema(
        tags=['标签'],
        summary="更新标签",
        description="更新标签信息。"
    ),
    partial_update=extend_schema(
        tags=['标签'],
        summary="部分更新标签",
        description="部分更新标签信息。"
    ),
    destroy=extend_schema(
        tags=['标签'],
        summary="删除标签",
        description="删除标签。删除后，使用该标签的链接不会被删除，只是标签关联被移除。"
    ),
)
class TagViewSet(viewsets.ModelViewSet):
    """ViewSet for managing link tags."""
    serializer_class = TagSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Return only tags belonging to the authenticated user."""
        return Tag.objects.filter(user=self.request.user).order_by('name')
    
    def perform_create(self, serializer):
        """Set the user when creating a tag."""
        serializer.save(user=self.request.user)
