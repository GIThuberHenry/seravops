from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings
from app.core.security import get_client_ip, is_ip_allowed
from app.main import create_app


def test_is_ip_allowed():
    # Empty or None allows all
    assert is_ip_allowed("1.2.3.4", None)
    assert is_ip_allowed("1.2.3.4", "")
    assert is_ip_allowed("2001:db8::1", "")

    # Exact single IP
    whitelist = "192.168.1.100, 10.0.0.1"
    assert is_ip_allowed("192.168.1.100", whitelist)
    assert is_ip_allowed("10.0.0.1", whitelist)
    assert not is_ip_allowed("192.168.1.101", whitelist)
    assert not is_ip_allowed("8.8.8.8", whitelist)

    # CIDR blocks
    cidr_whitelist = "192.168.1.0/24, 10.0.0.0/8"
    assert is_ip_allowed("192.168.1.1", cidr_whitelist)
    assert is_ip_allowed("192.168.1.254", cidr_whitelist)
    assert is_ip_allowed("10.254.1.99", cidr_whitelist)
    assert not is_ip_allowed("192.168.2.1", cidr_whitelist)
    assert not is_ip_allowed("172.16.0.1", cidr_whitelist)

    # Invalid client IP
    assert not is_ip_allowed("not-an-ip", "192.168.1.0/24")


def test_get_client_ip():
    # 1. X-Forwarded-For header
    req = MagicMock()
    req.headers = {"X-Forwarded-For": "203.0.113.195, 70.41.3.18, 150.172.238.178"}
    assert get_client_ip(req) == "203.0.113.195"

    # 2. X-Real-IP header
    req = MagicMock()
    req.headers = {"X-Real-IP": "198.51.100.22"}
    assert get_client_ip(req) == "198.51.100.22"

    # 3. Direct client host
    req = MagicMock()
    req.headers = {}
    req.client.host = "192.168.1.5"
    assert get_client_ip(req) == "192.168.1.5"


@pytest.mark.asyncio
async def test_production_jwt_secret_validation():
    # In non-debug mode with default secret, app creation should raise RuntimeError during lifespan
    with patch("app.main.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            debug=False,
            jwt_secret="change-me-in-production",
        )
        app = create_app()
        with pytest.raises(RuntimeError) as exc_info:
            async with app.router.lifespan_context(app):
                pass
        assert "FATAL SECURITY CONFIGURATION" in str(exc_info.value)
