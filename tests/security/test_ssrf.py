import httpx
import pytest
import respx

from shared.http import SafeHttpClient
from shared.ssrf import SSRFError, is_public_address, validate_url


def public(_h):
    return ["93.184.216.34"]


@pytest.mark.parametrize(
    "addr",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.5.4",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "2002:7f00:0001::1",
        "240.0.0.1",
    ],
)
def test_non_public_addresses_rejected(addr):
    assert not is_public_address(addr)


def test_public_address_accepted():
    assert is_public_address("93.184.216.34")
    assert is_public_address("2606:4700::1111")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://localhost/",
        "http://foo.internal/",
        "http://user:pw@example.com/",
        "http://example.com:22/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
    ],
)
def test_bad_urls_rejected(url):
    with pytest.raises(SSRFError):
        validate_url(url, resolver=public)


def test_hostname_resolving_to_private_ip_rejected():
    with pytest.raises(SSRFError):
        validate_url("https://evil.example/", resolver=lambda h: ["10.1.2.3"])
    # any private answer among several is enough to reject (DNS round-robin trick)
    with pytest.raises(SSRFError):
        validate_url("https://evil.example/", resolver=lambda h: ["93.184.216.34", "127.0.0.1"])


async def test_redirect_to_private_address_blocked():
    def resolver(host):
        return ["10.0.0.5"] if host == "internal.example" else ["93.184.216.34"]

    client = SafeHttpClient(user_agent="t", resolver=resolver, pin_dns=False)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://public.example/").mock(
            return_value=httpx.Response(302, headers={"location": "https://internal.example/admin"})
        )
        with pytest.raises(SSRFError):
            await client.get("https://public.example/")
    await client.aclose()


async def test_response_size_limit():
    from shared.http import ResponseTooLarge

    client = SafeHttpClient(user_agent="t", resolver=public, pin_dns=False, max_bytes=100)
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://big.example/").mock(return_value=httpx.Response(200, content=b"x" * 1000))
        with pytest.raises(ResponseTooLarge):
            await client.get("https://big.example/")
    await client.aclose()


async def test_dns_pinning_connects_to_validated_ip(monkeypatch):
    monkeypatch.setattr("urllib.request.getproxies", lambda: {})
    client = SafeHttpClient(user_agent="t", resolver=public, pin_dns=True)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://93.184.216.34/x").mock(return_value=httpx.Response(200, text="ok"))
        resp = await client.get("https://pinned.example/x")
        assert resp.status_code == 200
        req = route.calls[0].request
        assert req.headers["host"] == "pinned.example"
        assert req.extensions.get("sni_hostname") == "pinned.example"
    await client.aclose()
