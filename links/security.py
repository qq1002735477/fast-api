"""
URL Security Service for the links app.

Provides URL safety validation against malicious domain blacklists
and input sanitization to prevent XSS and SQL injection attacks.

Requirements: 11.1, 11.2, 11.5
"""
import re
import html
import logging
from typing import Optional, Set
from urllib.parse import urlparse

from django.conf import settings

logger = logging.getLogger(__name__)


# Default malicious domain blacklist
DEFAULT_MALICIOUS_DOMAINS: Set[str] = {
    # Known phishing domains (examples)
    'malware.com',
    'phishing-site.com',
    'evil-domain.net',
    'scam-website.org',
    'fake-login.com',
    'steal-credentials.net',
    'malicious-download.com',
    'virus-host.org',
    'trojan-site.net',
    'ransomware-host.com',
    # Add more known malicious domains as needed
}


class URLSecurityService:
    """
    Service for checking URL safety and sanitizing user input.
    
    Provides:
    - Malicious domain blacklist checking
    - Input sanitization for XSS prevention
    - SQL injection pattern detection
    """
    
    def __init__(self):
        """Initialize the security service with configurable blacklist."""
        # Load blacklist from settings or use default
        self.malicious_domains = getattr(
            settings, 
            'MALICIOUS_DOMAIN_BLACKLIST', 
            DEFAULT_MALICIOUS_DOMAINS
        )
        
        # Compile regex patterns for efficiency
        self._compile_patterns()
    
    def _compile_patterns(self):
        """Compile regex patterns for input validation."""
        # XSS patterns to detect
        self.xss_patterns = [
            re.compile(r'<script[^>]*>.*?</script>', re.IGNORECASE | re.DOTALL),
            re.compile(r'javascript:', re.IGNORECASE),
            re.compile(r'on\w+\s*=', re.IGNORECASE),  # onclick=, onload=, etc.
            re.compile(r'<iframe[^>]*>', re.IGNORECASE),
            re.compile(r'<object[^>]*>', re.IGNORECASE),
            re.compile(r'<embed[^>]*>', re.IGNORECASE),
            re.compile(r'<svg[^>]*onload', re.IGNORECASE),
            re.compile(r'data:text/html', re.IGNORECASE),
            re.compile(r'vbscript:', re.IGNORECASE),
        ]
        
        # SQL injection patterns to detect
        self.sql_patterns = [
            re.compile(r"('\s*(or|and)\s*'?\d*'?\s*=\s*'?\d*)", re.IGNORECASE),
            re.compile(r'(;\s*(drop|delete|truncate|alter|update|insert)\s+)', re.IGNORECASE),
            re.compile(r'(union\s+(all\s+)?select)', re.IGNORECASE),
            re.compile(r"(--\s*$|/\*.*\*/)", re.IGNORECASE),
            re.compile(r"('\s*;\s*--)", re.IGNORECASE),
            re.compile(r'(exec\s*\(|execute\s*\()', re.IGNORECASE),
            re.compile(r'(xp_cmdshell|sp_executesql)', re.IGNORECASE),
        ]
    
    def extract_domain(self, url: str) -> Optional[str]:
        """
        Extract the domain from a URL.
        
        Args:
            url: The URL to extract domain from.
        
        Returns:
            The domain string or None if extraction fails.
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            # Remove port if present
            if ':' in domain:
                domain = domain.split(':')[0]
            
            # Remove www. prefix for consistent matching
            if domain.startswith('www.'):
                domain = domain[4:]
            
            return domain if domain else None
        except Exception:
            return None
    
    def is_domain_blacklisted(self, domain: str) -> bool:
        """
        Check if a domain is in the blacklist.
        
        Args:
            domain: The domain to check.
        
        Returns:
            True if blacklisted, False otherwise.
        """
        if not domain:
            return False
        
        domain = domain.lower()
        
        # Remove www. prefix for consistent matching
        if domain.startswith('www.'):
            domain = domain[4:]
        
        # Check exact match
        if domain in self.malicious_domains:
            return True
        
        # Check if it's a subdomain of a blacklisted domain
        for blacklisted in self.malicious_domains:
            if domain.endswith('.' + blacklisted):
                return True
        
        return False
    
    def is_url_safe(self, url: str) -> bool:
        """
        Check if a URL is safe (not in malicious domain blacklist).
        
        Args:
            url: The URL to check.
        
        Returns:
            True if safe, False if potentially malicious.
        """
        domain = self.extract_domain(url)
        
        if not domain:
            # Can't extract domain, consider unsafe
            return False
        
        is_blacklisted = self.is_domain_blacklisted(domain)
        
        if is_blacklisted:
            logger.warning(
                f"Malicious URL detected: {url} (domain: {domain})"
            )
        
        return not is_blacklisted
    
    def check_url_safety(self, url: str) -> dict:
        """
        Comprehensive URL safety check with detailed results.
        
        Args:
            url: The URL to check.
        
        Returns:
            Dict with 'is_safe', 'domain', and 'reason' keys.
        """
        domain = self.extract_domain(url)
        
        if not domain:
            return {
                'is_safe': False,
                'domain': None,
                'reason': 'Unable to extract domain from URL'
            }
        
        if self.is_domain_blacklisted(domain):
            logger.warning(
                f"Blocked malicious URL attempt: {url} (domain: {domain})"
            )
            return {
                'is_safe': False,
                'domain': domain,
                'reason': 'Domain is in malicious blacklist'
            }
        
        return {
            'is_safe': True,
            'domain': domain,
            'reason': None
        }
    
    def contains_xss(self, input_str: str) -> bool:
        """
        Check if input contains potential XSS patterns.
        
        Args:
            input_str: The input string to check.
        
        Returns:
            True if XSS patterns detected, False otherwise.
        """
        if not input_str:
            return False
        
        for pattern in self.xss_patterns:
            if pattern.search(input_str):
                return True
        
        return False
    
    def contains_sql_injection(self, input_str: str) -> bool:
        """
        Check if input contains potential SQL injection patterns.
        
        Args:
            input_str: The input string to check.
        
        Returns:
            True if SQL injection patterns detected, False otherwise.
        """
        if not input_str:
            return False
        
        for pattern in self.sql_patterns:
            if pattern.search(input_str):
                return True
        
        return False
    
    def sanitize_input(self, input_str: str) -> str:
        """
        Sanitize user input to prevent XSS attacks.
        
        This method:
        - HTML-escapes special characters
        - Removes or escapes potentially dangerous content
        
        Args:
            input_str: The input string to sanitize.
        
        Returns:
            Sanitized string safe for display.
        """
        if not input_str:
            return input_str
        
        # HTML escape special characters
        sanitized = html.escape(input_str, quote=True)
        
        return sanitized
    
    def validate_input(self, input_str: str) -> dict:
        """
        Validate user input for security threats.
        
        Args:
            input_str: The input string to validate.
        
        Returns:
            Dict with 'is_valid', 'has_xss', 'has_sql_injection', 'sanitized' keys.
        """
        if not input_str:
            return {
                'is_valid': True,
                'has_xss': False,
                'has_sql_injection': False,
                'sanitized': input_str
            }
        
        has_xss = self.contains_xss(input_str)
        has_sql_injection = self.contains_sql_injection(input_str)
        sanitized = self.sanitize_input(input_str)
        
        if has_xss:
            logger.warning(f"XSS attempt detected in input: {input_str[:100]}...")
        
        if has_sql_injection:
            logger.warning(f"SQL injection attempt detected in input: {input_str[:100]}...")
        
        return {
            'is_valid': not (has_xss or has_sql_injection),
            'has_xss': has_xss,
            'has_sql_injection': has_sql_injection,
            'sanitized': sanitized
        }
    
    def add_to_blacklist(self, domain: str) -> bool:
        """
        Add a domain to the blacklist (runtime only).
        
        Args:
            domain: The domain to add.
        
        Returns:
            True if added, False if already exists.
        """
        domain = domain.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        if domain in self.malicious_domains:
            return False
        
        self.malicious_domains.add(domain)
        logger.info(f"Added domain to blacklist: {domain}")
        return True
    
    def remove_from_blacklist(self, domain: str) -> bool:
        """
        Remove a domain from the blacklist (runtime only).
        
        Args:
            domain: The domain to remove.
        
        Returns:
            True if removed, False if not found.
        """
        domain = domain.lower()
        if domain.startswith('www.'):
            domain = domain[4:]
        
        if domain not in self.malicious_domains:
            return False
        
        self.malicious_domains.discard(domain)
        logger.info(f"Removed domain from blacklist: {domain}")
        return True


# Singleton instance for convenience
url_security_service = URLSecurityService()
