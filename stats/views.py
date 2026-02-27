"""
Views for the stats app.

Provides export API endpoints for authenticated users.

Requirements: 12.1, 12.2
"""
import os
import mimetypes

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.http import FileResponse, Http404
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiExample

from .models import ExportTask
from .serializers import ExportTaskSerializer, ExportStatusResponseSerializer
from .export_service import export_service


class ExportCreateView(APIView):
    """
    Create a new export task.
    
    POST /api/export/
    
    Requirements: 12.1, 12.2
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        tags=['数据导出'],
        summary="请求数据导出",
        description="""
创建数据导出任务，生成包含所有链接数据的 CSV 文件。

### 导出内容
- 短码
- 原始 URL
- 创建时间
- 过期时间
- 点击量
- 分组
- 标签

### 处理方式
- 链接数 < 100: 同步处理，立即返回下载链接
- 链接数 >= 100: 异步处理，需轮询状态接口
        """,
        responses={
            201: OpenApiResponse(
                response=ExportTaskSerializer,
                description="导出任务创建成功",
                examples=[
                    OpenApiExample(
                        '同步完成',
                        value={
                            'id': 1,
                            'status': 'completed',
                            'total_links': 50,
                            'error_message': '',
                            'created_at': '2024-01-15T10:00:00Z',
                            'completed_at': '2024-01-15T10:00:05Z',
                            'download_url': '/api/export/1/download/'
                        }
                    ),
                    OpenApiExample(
                        '异步处理中',
                        value={
                            'id': 2,
                            'status': 'processing',
                            'total_links': 500,
                            'error_message': '',
                            'created_at': '2024-01-15T10:00:00Z',
                            'completed_at': None
                        }
                    )
                ]
            ),
        }
    )
    def post(self, request):
        """Create a new export task."""
        user = request.user
        
        # Create the export task
        task = export_service.create_export_task(user)
        
        # Check if we should process async or sync
        if task.total_links < 100:
            try:
                export_service.generate_csv(user, task)
                task.refresh_from_db()
            except Exception as e:
                pass
        else:
            try:
                from .tasks import process_export_task
                process_export_task.delay(task.id)
            except ImportError:
                try:
                    export_service.generate_csv(user, task)
                    task.refresh_from_db()
                except Exception:
                    pass
        
        serializer = ExportTaskSerializer(task)
        response_data = serializer.data
        
        if task.status == 'completed':
            response_data['download_url'] = f'/api/export/{task.id}/download/'
        
        return Response(response_data, status=status.HTTP_201_CREATED)


class ExportStatusView(APIView):
    """
    Get export task status.
    
    GET /api/export/{task_id}/
    
    Requirements: 12.2
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        tags=['数据导出'],
        summary="查询导出状态",
        description="""
查询导出任务的当前状态。

### 状态说明
- `pending`: 等待处理
- `processing`: 处理中
- `completed`: 已完成，可下载
- `failed`: 处理失败
        """,
        responses={
            200: OpenApiResponse(
                response=ExportStatusResponseSerializer,
                description="任务状态"
            ),
            404: OpenApiResponse(description="任务不存在"),
        }
    )
    def get(self, request, task_id):
        """Get export task status."""
        user = request.user
        
        task = export_service.get_export_task(task_id, user)
        if not task:
            return Response(
                {'error': 'Export task not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = ExportTaskSerializer(task)
        response_data = serializer.data
        
        if task.status == 'completed' and task.file_path:
            response_data['download_url'] = f'/api/export/{task.id}/download/'
        
        return Response(response_data)


class ExportDownloadView(APIView):
    """
    Download export file.
    
    GET /api/export/{task_id}/download/
    
    Requirements: 12.1
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        tags=['数据导出'],
        summary="下载导出文件",
        description="下载已完成的导出任务生成的 CSV 文件。",
        responses={
            200: OpenApiResponse(description="CSV 文件下载"),
            400: OpenApiResponse(description="导出尚未完成"),
            404: OpenApiResponse(description="任务不存在或文件不存在"),
        }
    )
    def get(self, request, task_id):
        """Download the export file."""
        user = request.user
        
        task = export_service.get_export_task(task_id, user)
        if not task:
            return Response(
                {'error': 'Export task not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if task.status != 'completed':
            return Response(
                {'error': f'Export is not ready. Current status: {task.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        file_path = export_service.get_file_path(task)
        if not file_path:
            return Response(
                {'error': 'Export file not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        filename = os.path.basename(file_path)
        
        response = FileResponse(
            open(file_path, 'rb'),
            content_type='text/csv'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response


class ExportListView(APIView):
    """
    List user's export tasks.
    
    GET /api/export/
    """
    permission_classes = [IsAuthenticated]
    
    @extend_schema(
        tags=['数据导出'],
        summary="获取导出任务列表",
        description="获取当前用户最近的导出任务列表（最多 10 条）。",
        responses={
            200: OpenApiResponse(
                response=ExportTaskSerializer(many=True),
                description="导出任务列表"
            ),
        }
    )
    def get(self, request):
        """List recent export tasks."""
        user = request.user
        
        tasks = export_service.get_user_export_tasks(user, limit=10)
        serializer = ExportTaskSerializer(tasks, many=True)
        
        response_data = []
        for i, task in enumerate(tasks):
            task_data = serializer.data[i]
            if task.status == 'completed' and task.file_path:
                task_data['download_url'] = f'/api/export/{task.id}/download/'
            response_data.append(task_data)
        
        return Response(response_data)
