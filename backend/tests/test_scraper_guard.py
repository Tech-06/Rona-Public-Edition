from toolbox.tools.web_scraper import _blocked_reason


def test_blocks_loopback():
    assert _blocked_reason("http://127.0.0.1/") is not None
    assert _blocked_reason("http://localhost/") is not None


def test_blocks_rfc1918_private_ranges():
    assert _blocked_reason("http://10.0.0.1/") is not None
    assert _blocked_reason("http://172.16.0.1/") is not None
    assert _blocked_reason("http://192.168.1.1/") is not None


def test_blocks_link_local_and_cloud_metadata_address():
    assert _blocked_reason("http://169.254.169.254/") is not None


def test_blocks_tailscale_cgnat_range():
    assert _blocked_reason("http://100.64.0.5/") is not None
    assert _blocked_reason("http://100.100.100.100/") is not None


def test_allows_addresses_outside_the_cgnat_range():
    assert _blocked_reason("http://100.63.255.255/") is None
    assert _blocked_reason("http://100.128.0.1/") is None


def test_rejects_non_http_schemes():
    assert _blocked_reason("file:///etc/passwd") is not None
    assert _blocked_reason("ftp://example.com/") is not None


def test_allows_a_public_address():
    assert _blocked_reason("http://8.8.8.8/") is None
