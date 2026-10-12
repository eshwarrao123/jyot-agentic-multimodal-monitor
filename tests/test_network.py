"""
Tests for defensive network access, SSRF prevention, and attachment validation.
"""

import ipaddress
from pathlib import Path
import pytest
import respx
import httpx

from jyot_monitor.ingestion.network import (
    SafeHttpClient,
    SecurityError,
    ResponseTooLargeError,
    InvalidFileSignatureError,
    PDFPageLimitExceededError,
    is_ip_prohibited,
    validate_url,
    validate_file_signature,
    check_pdf_page_limit,
)


def test_validate_url_scheme_and_format():
    """Verify validate_url enforces HTTPS, blocks credentials and ports."""
    # Valid HTTPS
    validate_url("https://www.cpsc.gov/recalls")
    validate_url("https://www.fda.gov/news")

    # Invalid scheme (HTTP disallowed by default)
    with pytest.raises(SecurityError, match="Disallowed URL scheme"):
        validate_url("http://www.cpsc.gov/recalls")

    # Dangerous schemes
    for bad in ["file:///etc/passwd", "ftp://example.com/data", "gopher://example.com"]:
        with pytest.raises(SecurityError, match="Disallowed URL scheme"):
            validate_url(bad)

    # Rejection of user credentials in URL
    with pytest.raises(SecurityError, match="Credentials embedded"):
        validate_url("https://admin:secret@www.cpsc.gov/recalls")

    # Rejection of non-standard port
    with pytest.raises(SecurityError, match="port 8080 blocked"):
        validate_url("https://www.cpsc.gov:8080/recalls")


def test_validate_url_host_allowlist():
    """Verify validate_url enforces host allowlist strictly."""
    allowed = ["www.cpsc.gov", "cpsc.gov"]
    
    # Matching hosts
    validate_url("https://www.cpsc.gov/recalls", allowed_hosts=allowed)
    validate_url("https://cpsc.gov/recalls", allowed_hosts=allowed)

    # Disallowed hosts
    with pytest.raises(SecurityError, match="not in configured allowlist"):
        validate_url("https://malicious.org/feed", allowed_hosts=allowed)

    # Subdomain spoofing attempt
    with pytest.raises(SecurityError, match="not in configured allowlist"):
        validate_url("https://www.cpsc.gov.attacker.com/recalls", allowed_hosts=allowed)


def test_prohibited_ip_detection():
    """Verify is_ip_prohibited blocks loopback, private, link-local, and reserved ranges."""
    prohibited_ips = [
        "127.0.0.1",       # Loopback
        "127.0.1.1",       # Loopback range
        "10.0.0.1",        # RFC 1918 Private
        "172.16.5.10",     # RFC 1918 Private
        "192.168.1.1",     # RFC 1918 Private
        "169.254.169.254", # Cloud metadata / Link-local
        "100.64.0.1",      # Carrier-Grade NAT (RFC 6598)
        "192.0.2.1",       # TEST-NET-1 Documentation
        "224.0.0.1",       # Multicast
        "240.0.0.1",       # Reserved
        "0.0.0.0",         # Unspecified
        "::1",             # IPv6 Loopback
        "fe80::1",         # IPv6 Link-local
        "fc00::1",         # IPv6 Unique Local
    ]
    for ip_str in prohibited_ips:
        ip = ipaddress.ip_address(ip_str)
        assert is_ip_prohibited(ip), f"IP {ip_str} should be prohibited"

    # Public IP should not be prohibited
    assert not is_ip_prohibited(ipaddress.ip_address("8.8.8.8"))
    assert not is_ip_prohibited(ipaddress.ip_address("151.101.1.140"))


def test_offline_mode_network_isolation():
    """Verify SafeHttpClient fails closed in offline mode."""
    client = SafeHttpClient(offline_mode=True)
    with pytest.raises(SecurityError, match="Offline mode is active"):
        client.get("https://www.cpsc.gov/recalls")


@respx.mock
def test_streaming_response_size_ceiling():
    """Verify SafeHttpClient enforces response byte limit even if Content-Length is absent."""
    # Chunked response without Content-Length exceeding 100 bytes
    large_payload = b"A" * 500
    respx.get("https://www.cpsc.gov/large").respond(
        status_code=200,
        content=large_payload,
        headers={"Content-Type": "application/xml"},
    )

    client = SafeHttpClient(max_bytes=100)
    with pytest.raises(ResponseTooLargeError, match="exceeds limit of 100 bytes"):
        client.get("https://www.cpsc.gov/large", allowed_hosts=["www.cpsc.gov"])


@respx.mock
def test_redirect_revalidation_blocks_disallowed_target():
    """Verify manual redirect handler revalidates redirect targets against allowlist."""
    # Redirects from allowed host to external untrusted host
    respx.get("https://www.cpsc.gov/redirect").respond(
        status_code=302,
        headers={"Location": "https://attacker.evil/trap"},
    )

    client = SafeHttpClient()
    with pytest.raises(SecurityError, match="not in configured allowlist"):
        client.get("https://www.cpsc.gov/redirect", allowed_hosts=["www.cpsc.gov"])


def test_validate_file_signature():
    """Verify validate_file_signature checks magic bytes for PNG, JPEG, PDF."""
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 30
    pdf_bytes = b"%PDF-1.4\n" + b"\x00" * 30

    # Valid signatures
    validate_file_signature(png_bytes, expected_extension=".png")
    validate_file_signature(jpeg_bytes, expected_extension=".jpg")
    validate_file_signature(pdf_bytes, expected_extension=".pdf")

    # Mismatched/corrupted signatures
    with pytest.raises(InvalidFileSignatureError, match="signature mismatch"):
        validate_file_signature(b"NOT_A_PNG", expected_extension=".png")

    with pytest.raises(InvalidFileSignatureError, match="signature mismatch"):
        validate_file_signature(b"\x00\x01\x02\x03", expected_extension=".jpg")

    with pytest.raises(InvalidFileSignatureError, match="signature mismatch"):
        validate_file_signature(b"<html>Disguised HTML</html>", expected_extension=".pdf")


def test_pdf_page_limit_enforcement(tmp_path: Path):
    """Verify check_pdf_page_limit validates page count using pypdf."""
    from pypdf import PdfWriter

    # Create a small 2-page PDF
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    
    pdf_path = tmp_path / "test.pdf"
    with open(pdf_path, "wb") as f:
        writer.write(f)
    
    pdf_bytes = pdf_path.read_bytes()

    # Pass limit of 5 pages
    page_count = check_pdf_page_limit(pdf_bytes, max_pages=5)
    assert page_count == 2

    # Fail limit of 1 page
    with pytest.raises(PDFPageLimitExceededError, match="exceeds limit of 1 pages"):
        check_pdf_page_limit(pdf_bytes, max_pages=1)
