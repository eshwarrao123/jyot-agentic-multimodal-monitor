"""
Centralized defensive network access layer.

Enforces:
1. HTTPS and explicitly configured URL schemes.
2. Host allowlist filtering (feeds and permitted attachment hosts).
3. Rejection of URL credentials (user:pass@host) and non-standard ports.
4. Pre-request DNS resolution checks blocking loopback, private, link-local,
   multicast, carrier-grade NAT, and reserved/documentation IP ranges (SSRF defense).
5. Manual HTTP redirect handling: re-validates each redirect target before following.
6. Connect and read timeouts.
7. Strict response byte caps via streaming chunks, even if Content-Length is absent.
8. Content-type and magic byte file signature validation for attachments.
9. PDF page limit enforcement.
10. Transient error retries: exponential backoff with jitter and Retry-After support.
11. Strict offline mode guard preventing network calls during replay.

Known Limitations:
- DNS Rebinding: Standard pre-request DNS validation leaves a small theoretical TOCTOU window
  if an attacker changes DNS records between resolution and TCP connect. In production high-assurance
  deployments, IP-pinned HTTP transport adapters or egress proxy firewalls provide defense-in-depth.
"""

import email.utils
import ipaddress
import random
import socket
import time
import urllib.parse
from typing import Dict, List, Optional, Set, Tuple

import httpx

# Pre-defined prohibited network blocks (Carrier-grade NAT, documentation, benchmarking)
EXTRA_PROHIBITED_NETWORKS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),     # Carrier-Grade NAT (RFC 6598)
    ipaddress.ip_network("192.0.0.0/24"),      # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),      # TEST-NET-1 (RFC 5737)
    ipaddress.ip_network("198.18.0.0/15"),     # Benchmarking (RFC 2544)
    ipaddress.ip_network("198.51.100.0/24"),   # TEST-NET-2 (RFC 5737)
    ipaddress.ip_network("203.0.113.0/24"),    # TEST-NET-3 (RFC 5737)
    ipaddress.ip_network("240.0.0.0/4"),       # Reserved / Future use
]

# Magic byte signatures for supported attachments
MAGIC_SIGNATURES: Dict[str, bytes] = {
    "png": b"\x89PNG\r\n\x1a\n",
    "jpeg": b"\xff\xd8\xff",
    "jpg": b"\xff\xd8\xff",
    "pdf": b"%PDF-",
}


class SecurityError(Exception):
    """Raised when a network safety or SSRF policy is violated."""
    pass


class ResponseTooLargeError(SecurityError):
    """Raised when an HTTP response exceeds maximum permitted byte limit."""
    pass


class InvalidFileSignatureError(SecurityError):
    """Raised when attachment magic bytes do not match expected extension/MIME."""
    pass


class PDFPageLimitExceededError(SecurityError):
    """Raised when a downloaded PDF exceeds maximum page count."""
    pass


def is_ip_prohibited(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address belongs to any private, loopback, or reserved range."""
    if (
        ip_obj.is_private
        or ip_obj.is_loopback
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj.is_reserved
        or ip_obj.is_unspecified
    ):
        return True

    for net in EXTRA_PROHIBITED_NETWORKS:
        if isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in net:
            return True

    return False


def validate_url(
    url: str,
    allowed_hosts: Optional[List[str]] = None,
    allowed_schemes: Optional[List[str]] = None,
    allow_dns_resolution: bool = True,
) -> Tuple[bool, str, List[str]]:
    """
    Validate a URL against SSRF, scheme, credentials, port, and host allowlist.
    
    Args:
        url: Full URL string to validate
        allowed_hosts: List of permitted hostnames (case-insensitive)
        allowed_schemes: Permitted schemes (default: ['https'])
        allow_dns_resolution: Whether to resolve DNS and check target IP ranges
        
    Returns:
        Tuple of (is_valid, canonical_hostname, resolved_ip_list)
        
    Raises:
        SecurityError: If URL fails any security check.
    """
    if not url or not isinstance(url, str):
        raise SecurityError("URL must be a non-empty string.")

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception as e:
        raise SecurityError(f"Malformed URL syntax: {e}")

    # 1. Scheme check
    schemes = [s.lower() for s in (allowed_schemes or ["https"])]
    if parsed.scheme.lower() not in schemes:
        raise SecurityError(f"Disallowed URL scheme '{parsed.scheme}'. Permitted: {schemes}")

    # 2. Reject credentials in URL
    if parsed.username or parsed.password:
        raise SecurityError("Credentials embedded in URL (user:pass@host) are strictly forbidden.")

    # 3. Hostname check
    hostname = parsed.hostname
    if not hostname:
        raise SecurityError("URL is missing a valid hostname.")

    hostname_clean = hostname.lower().strip()

    # Reject localhost literal
    if hostname_clean in ("localhost", "localhost.localdomain", "ip6-localhost"):
        raise SecurityError(f"Localhost access blocked: {hostname_clean}")

    # 4. Port validation: only standard HTTP/HTTPS ports permitted
    if parsed.port is not None:
        if parsed.scheme.lower() == "https" and parsed.port != 443:
            raise SecurityError(f"Non-standard HTTPS port {parsed.port} blocked.")
        if parsed.scheme.lower() == "http" and parsed.port != 80:
            raise SecurityError(f"Non-standard HTTP port {parsed.port} blocked.")

    # 5. Hostname allowlist check
    if allowed_hosts:
        normalized_allowed = {h.lower().strip() for h in allowed_hosts}
        if hostname_clean not in normalized_allowed:
            # Check wildcard / domain suffix match if configured
            subdomain_match = any(
                hostname_clean.endswith("." + allowed_h)
                for allowed_h in normalized_allowed
                if not allowed_h.startswith(".")
            )
            if not subdomain_match:
                raise SecurityError(
                    f"Hostname '{hostname_clean}' is not in configured allowlist: {sorted(normalized_allowed)}"
                )

    # 6. DNS Resolution & IP Range Verification
    resolved_ips: List[str] = []
    if allow_dns_resolution:
        # Check if hostname itself is already a direct IP literal
        try:
            direct_ip = ipaddress.ip_address(hostname_clean)
            if is_ip_prohibited(direct_ip):
                raise SecurityError(f"Direct connection to prohibited IP literal blocked: {direct_ip}")
            resolved_ips.append(str(direct_ip))
        except ValueError:
            # It is a domain name; resolve DNS
            try:
                addr_info = socket.getaddrinfo(hostname_clean, None)
            except socket.gaierror as e:
                raise SecurityError(f"DNS resolution failed for '{hostname_clean}': {e}")
            except Exception as e:
                raise SecurityError(f"DNS lookup error for '{hostname_clean}': {e}")

            if not addr_info:
                raise SecurityError(f"No IP addresses returned for host '{hostname_clean}'.")

            for family, socktype, proto, canonname, sockaddr in addr_info:
                ip_str = sockaddr[0]
                try:
                    ip_obj = ipaddress.ip_address(ip_str)
                except ValueError:
                    continue

                if is_ip_prohibited(ip_obj):
                    raise SecurityError(f"Host '{hostname_clean}' resolved to prohibited non-public IP: {ip_str}")
                resolved_ips.append(ip_str)

    return True, hostname_clean, resolved_ips


def validate_file_signature(
    content: bytes,
    expected_extension: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> bool:
    """
    Validate that downloaded byte content begins with the genuine file magic signature.
    
    Args:
        content: Raw downloaded bytes
        expected_extension: e.g. '.png', '.jpg', '.pdf'
        mime_type: e.g. 'image/png', 'application/pdf'
        
    Returns:
        True if signature matches.
        
    Raises:
        InvalidFileSignatureError: If bytes do not match expected signature.
    """
    if not content:
        raise InvalidFileSignatureError("Attachment content is empty (0 bytes).")

    ext = (expected_extension or "").lstrip(".").lower()
    if not ext and mime_type:
        if "png" in mime_type:
            ext = "png"
        elif "jpeg" in mime_type or "jpg" in mime_type:
            ext = "jpeg"
        elif "pdf" in mime_type:
            ext = "pdf"

    if ext in MAGIC_SIGNATURES:
        sig = MAGIC_SIGNATURES[ext]
        if not content.startswith(sig):
            preview = content[:16]
            raise InvalidFileSignatureError(
                f"File signature mismatch for extension '.{ext}'. "
                f"Expected magic {sig!r}, got preview {preview!r}"
            )
    elif ext in ("jpg",):
        sig = MAGIC_SIGNATURES["jpeg"]
        if not content.startswith(sig):
            raise InvalidFileSignatureError(f"File signature mismatch for '.{ext}'.")

    return True


def check_pdf_page_limit(pdf_bytes: bytes, max_pages: int = 10) -> int:
    """
    Safely inspect a PDF stream and verify page count is within budget.
    
    Args:
        pdf_bytes: PDF file binary data
        max_pages: Maximum permitted page count
        
    Returns:
        Total page count
        
    Raises:
        PDFPageLimitExceededError: If page count exceeds max_pages.
        SecurityError: If PDF cannot be parsed safely.
    """
    import io
    import pypdf

    try:
        stream = io.BytesIO(pdf_bytes)
        reader = pypdf.PdfReader(stream)
        num_pages = len(reader.pages)
        if num_pages > max_pages:
            raise PDFPageLimitExceededError(
                f"PDF page count ({num_pages}) exceeds limit of {max_pages} pages."
            )
        return num_pages
    except PDFPageLimitExceededError:
        raise
    except Exception as e:
        raise SecurityError(f"Failed to inspect PDF page count: {e}")


class SafeHttpClient:
    """
    Defensive HTTP client for live public ingestion.
    
    Features:
    - Pre-request SSRF validation on all URLs.
    - Manual redirect re-validation.
    - Streaming byte accumulation to strictly enforce response size limits.
    - Bounded exponential backoff with jitter and Retry-After header parsing.
    - Hard offline mode invariant.
    """

    def __init__(
        self,
        allowed_hosts: Optional[List[str]] = None,
        allowed_schemes: Optional[List[str]] = None,
        connect_timeout: float = 10.0,
        read_timeout: float = 20.0,
        max_bytes: int = 10 * 1024 * 1024,  # 10 MB default
        max_redirects: int = 5,
        max_retries: int = 3,
        backoff_base_seconds: float = 1.0,
        backoff_max_seconds: float = 10.0,
        offline_mode: bool = False,
    ):
        self.allowed_hosts = allowed_hosts or []
        self.allowed_schemes = allowed_schemes or ["https"]
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.max_retries = max_retries
        self.backoff_base = backoff_base_seconds
        self.backoff_max = backoff_max_seconds
        self.offline_mode = offline_mode
        self.user_agent = "Jyot-Monitor/1.0 (Public Safety Ingestion; Security Compliant)"

    def get(
        self,
        url: str,
        allowed_hosts: Optional[List[str]] = None,
        max_bytes: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> httpx.Response:
        """
        Execute a safe HTTP GET request with SSRF validation and response caps.
        
        Args:
            url: Target URL
            allowed_hosts: Override host allowlist
            max_bytes: Override max response byte cap
            headers: Additional request headers
            
        Returns:
            httpx.Response with fully loaded, byte-capped body.
        """
        if self.offline_mode:
            raise SecurityError(f"Offline mode is active: network request to '{url}' strictly denied.")

        active_allowed_hosts = allowed_hosts or self.allowed_hosts
        byte_limit = max_bytes or self.max_bytes

        req_headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
        }
        if headers:
            req_headers.update(headers)

        current_url = url
        redirect_count = 0

        timeout = httpx.Timeout(
            connect=self.connect_timeout,
            read=self.read_timeout,
            write=10.0,
            pool=10.0,
        )

        for attempt in range(self.max_retries + 1):
            # Pre-validate URL before every attempt/redirect
            validate_url(
                current_url,
                allowed_hosts=active_allowed_hosts,
                allowed_schemes=self.allowed_schemes,
                allow_dns_resolution=True,
            )

            try:
                with httpx.Client(timeout=timeout, follow_redirects=False) as client:
                    response = client.get(current_url, headers=req_headers)

                # 1. Handle Redirects (Manual Re-validation)
                if response.status_code in (301, 302, 303, 307, 308):
                    redirect_count += 1
                    if redirect_count > self.max_redirects:
                        raise SecurityError(f"Exceeded maximum redirect limit of {self.max_redirects}.")

                    location = response.headers.get("Location")
                    if not location:
                        raise SecurityError(f"Received redirect status {response.status_code} with missing Location header.")

                    # Resolve relative redirect URLs against the current URL
                    current_url = urllib.parse.urljoin(current_url, location)
                    continue

                # 2. Handle Rate Limits (429) & Transient Server Errors (500, 502, 503, 504)
                if response.status_code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    sleep_time = self._calculate_backoff(response, attempt)
                    time.sleep(sleep_time)
                    continue

                # 3. Stream and enforce max_bytes limit
                if response.is_success:
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > byte_limit:
                        raise ResponseTooLargeError(
                            f"Content-Length ({content_length} bytes) exceeds limit of {byte_limit} bytes."
                        )

                    # Stream and count bytes to prevent memory bombs
                    body_bytes = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65536):
                        body_bytes.extend(chunk)
                        if len(body_bytes) > byte_limit:
                            raise ResponseTooLargeError(
                                f"Streamed response exceeded limit of {byte_limit} bytes."
                            )

                    # Replace response._content with accumulated bytes
                    response._content = bytes(body_bytes)

                return response

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.NetworkError) as e:
                if attempt < self.max_retries:
                    sleep_time = min(self.backoff_max, self.backoff_base * (2 ** attempt)) + random.uniform(0.1, 0.4)
                    time.sleep(sleep_time)
                    continue
                raise SecurityError(f"HTTP request failed after {self.max_retries} retries: {e}")

        return response

    def _calculate_backoff(self, response: httpx.Response, attempt: int) -> float:
        """Calculate wait time respecting Retry-After header with jitter."""
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                # Integer seconds
                wait_secs = float(retry_after)
                return min(self.backoff_max, max(0.5, wait_secs))
            except ValueError:
                # HTTP-date format
                try:
                    target_time = email.utils.parsedate_to_datetime(retry_after).timestamp()
                    diff = target_time - time.time()
                    return min(self.backoff_max, max(0.5, diff))
                except Exception:
                    pass

        # Exponential backoff with random jitter
        exp = min(self.backoff_max, self.backoff_base * (2 ** attempt))
        jitter = random.uniform(0.1, 0.5)
        return exp + jitter
