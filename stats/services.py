"""
Statistics services for link access analytics.

Provides functionality for:
- Total click count statistics
- Unique visitor statistics
- Time-based (daily) statistics
"""
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from links.models import Link, AccessLog


class StatsService:
    """
    Service for computing and retrieving link access statistics.
    
    Provides methods for:
    - Getting overall link statistics (clicks, unique visitors)
    - Getting daily statistics within a date range
    - Getting recent access logs
    """
    
    def get_link_stats(self, link: Link) -> Dict[str, Any]:
        """
        Get comprehensive statistics for a link.
        
        Args:
            link: The Link object to get statistics for.
        
        Returns:
            Dict containing:
            - click_count: Total number of clicks
            - unique_visitors: Number of unique IP addresses
            - recent_access_logs: List of recent access log entries
        """
        # Get unique visitors count (by IP address)
        unique_visitors = AccessLog.objects.filter(
            link=link
        ).values('ip_address').distinct().count()
        
        # Get recent access logs (last 10)
        recent_logs = self._get_recent_access_logs(link, limit=10)
        
        return {
            'click_count': link.click_count,
            'unique_visitors': unique_visitors,
            'recent_access_logs': recent_logs,
        }
    
    def get_daily_stats(
        self,
        link: Link,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[Dict[str, Any]]:
        """
        Get daily statistics for a link within a date range.
        
        Args:
            link: The Link object to get statistics for.
            start_date: Start date for the range (inclusive). Defaults to 30 days ago.
            end_date: End date for the range (inclusive). Defaults to today.
        
        Returns:
            List of dicts, each containing:
            - date: The date (YYYY-MM-DD format)
            - click_count: Number of clicks on that day
            - unique_visitors: Number of unique visitors on that day
        """
        # Set default date range if not provided
        if end_date is None:
            end_date = timezone.now().date()
        if start_date is None:
            start_date = end_date - timedelta(days=30)
        
        # Convert dates to datetime for filtering
        start_datetime = timezone.make_aware(
            datetime.combine(start_date, datetime.min.time())
        )
        end_datetime = timezone.make_aware(
            datetime.combine(end_date, datetime.max.time())
        )
        
        # Query access logs grouped by date
        daily_clicks = AccessLog.objects.filter(
            link=link,
            accessed_at__gte=start_datetime,
            accessed_at__lte=end_datetime
        ).annotate(
            date=TruncDate('accessed_at')
        ).values('date').annotate(
            click_count=Count('id'),
            unique_visitors=Count('ip_address', distinct=True)
        ).order_by('date')
        
        # Convert to list of dicts with formatted dates
        result = []
        for entry in daily_clicks:
            result.append({
                'date': entry['date'].strftime('%Y-%m-%d') if entry['date'] else None,
                'click_count': entry['click_count'],
                'unique_visitors': entry['unique_visitors'],
            })
        
        return result
    
    def _get_recent_access_logs(
        self,
        link: Link,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Get recent access logs for a link.
        
        Args:
            link: The Link object.
            limit: Maximum number of logs to return.
        
        Returns:
            List of access log entries as dicts.
        """
        recent_logs = AccessLog.objects.filter(
            link=link
        ).order_by('-accessed_at')[:limit]
        
        return [
            {
                'ip_address': log.ip_address,
                'user_agent': log.user_agent,
                'referer': log.referer,
                'accessed_at': log.accessed_at.isoformat(),
            }
            for log in recent_logs
        ]
    
    def get_total_clicks_for_user(self, user) -> int:
        """
        Get total click count across all links for a user.
        
        Args:
            user: The user object.
        
        Returns:
            Total click count.
        """
        from django.db.models import Sum
        result = Link.objects.filter(user=user).aggregate(
            total_clicks=Sum('click_count')
        )
        return result['total_clicks'] or 0
    
    def get_total_unique_visitors_for_user(self, user) -> int:
        """
        Get total unique visitors across all links for a user.
        
        Args:
            user: The user object.
        
        Returns:
            Total unique visitor count.
        """
        return AccessLog.objects.filter(
            link__user=user
        ).values('ip_address').distinct().count()


# Singleton instance for convenience
stats_service = StatsService()
