import hashlib
import sys
from pathlib import Path

import httpx
import pytest

from memoryseal.attested_transport import AttestedGatewayTransport


def test_pinned_subprocess_gates_inference_connection(tmp_path):
    certificate = b"synthetic gateway certificate"
    cert_digest = hashlib.sha256(certificate).hexdigest()
    verifier = tmp_path / "verifier"
    verifier.write_text(f"#!{sys.executable}\nprint('  served cert      {cert_digest}')\n")
    verifier.chmod(0o700)
    executable_digest = hashlib.sha256(verifier.read_bytes()).hexdigest()
    calls = []

    class Socket:
        def getpeercert(self, binary_form):
            assert binary_form
            return certificate

    class Response:
        status = 200

        def read(self, _limit):
            return b"{}"

        def getheaders(self):
            return [("content-type", "application/json")]

    class Connection:
        def __init__(self, *_args, **_kwargs):
            calls.append("created")
            self.sock = Socket()
            self.auto_open = True

        def connect(self):
            calls.append("connected")

        def request(self, _method, _path, *, body, headers):
            assert body == b"private" and headers["authorization"] == "Bearer secret"
            calls.append("sent")

        def getresponse(self):
            return Response()

        def close(self):
            pass

    url = "https://router-api-testnet.integratenetwork.work/v1/chat/completions"
    transport = AttestedGatewayTransport(
        verifier, "testnet", expected_sha256="0" * 64, connection_factory=Connection
    )
    with httpx.Client(transport=transport) as client, pytest.raises(httpx.TransportError):
        client.post(url, content=b"private", headers={"authorization": "Bearer secret"})
    assert calls == []

    transport = AttestedGatewayTransport(
        verifier, "testnet", expected_sha256=executable_digest, connection_factory=Connection
    )
    with httpx.Client(transport=transport) as client:
        assert (
            client.post(
                url, content=b"private", headers={"authorization": "Bearer secret"}
            ).status_code
            == 200
        )
    assert calls == ["created", "connected", "sent"]
    assert transport.verified_fingerprint == cert_digest


def test_tls_certificate_is_checked_before_private_request():
    certificate = b"example certificate"
    digest = hashlib.sha256(certificate).hexdigest()
    calls = []
    state = {
        "cert": certificate,
        "verdict": "passed",
        "output": f"  served cert      {digest}\n",
        "compressed": False,
    }

    def verifier(binary, network):
        assert binary == Path("/trusted/pcverify") and network == "testnet"
        return {"status": state["verdict"], "output": state["output"]}

    class Socket:
        def getpeercert(self, binary_form):
            assert binary_form
            return state["cert"]

    class Response:
        status = 200

        def read(self, limit):
            return b"{}"

        def getheaders(self):
            return (
                [("content-encoding", "gzip")]
                if state["compressed"]
                else [("content-type", "application/json")]
            )

    class Connection:
        def __init__(self, host, port, **kwargs):
            calls.append("created")
            self.sock = Socket()
            self.auto_open = True

        def connect(self):
            calls.append("connected")

        def request(self, method, path, body, headers):
            assert self.auto_open is False
            calls.append((method, path, body, headers["authorization"]))

        def getresponse(self):
            return Response()

        def close(self):
            calls.append("closed")

    transport = AttestedGatewayTransport(
        Path("/trusted/pcverify"), "testnet", verifier=verifier, connection_factory=Connection
    )
    with httpx.Client(transport=transport) as client:
        url = "https://router-api-testnet.integratenetwork.work/v1/chat/completions"
        state["verdict"] = "failed"
        with pytest.raises(httpx.TransportError):
            client.post(url, content=b"private", headers={"authorization": "Bearer secret"})
        assert calls == []
        state["verdict"] = "passed"
        state["cert"] = b"different certificate"
        with pytest.raises(httpx.TransportError):
            client.post(url, content=b"private", headers={"authorization": "Bearer secret"})
        assert not any(isinstance(call, tuple) for call in calls)
        state["cert"] = certificate
        assert (
            client.post(
                url, content=b"private", headers={"authorization": "Bearer secret"}
            ).status_code
            == 200
        )
        assert transport.verified_fingerprint == digest
        assert [call for call in calls if isinstance(call, tuple)] == [
            ("POST", "/v1/chat/completions", b"private", "Bearer secret")
        ]
        state["compressed"] = True
        with pytest.raises(httpx.TransportError, match="Compressed"):
            client.post(url, content=b"private", headers={"authorization": "Bearer secret"})
        assert transport.verified_fingerprint is None
        state["compressed"] = False
        state["output"] += state["output"]
        with pytest.raises(httpx.TransportError):
            client.post(url, content=b"private")
        assert transport.verified_fingerprint is None


def test_real_tls_connection_pins_before_sending(tmp_path, monkeypatch):
    import datetime
    import ipaddress
    import socket
    import ssl
    import threading
    from http.client import HTTPSConnection
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    host = "router-api-testnet.integratenetwork.work"
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName(host), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(
                (
                    self.headers.get("Authorization"),
                    self.rfile.read(int(self.headers["Content-Length"])),
                )
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    server.socket = server_context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_context = ssl.create_default_context
    monkeypatch.setattr(
        "memoryseal.attested_transport.ssl.create_default_context",
        lambda: original_context(cafile=str(cert_path)),
    )

    class LocalConnection(HTTPSConnection):
        def connect(self):
            raw = socket.create_connection(("127.0.0.1", server.server_port), timeout=3)
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)

    state = {"fingerprint": "0" * 63 + "1"}

    def verifier(*args):
        return {"status": "passed", "output": f"  served cert      {state['fingerprint']}\n"}

    try:
        transport = AttestedGatewayTransport(
            Path("/trusted/pcverify"),
            "testnet",
            verifier=verifier,
            connection_factory=LocalConnection,
        )
        with httpx.Client(transport=transport) as client:
            url = f"https://{host}/v1/chat/completions"
            with pytest.raises(httpx.TransportError):
                client.post(url, content=b"private", headers={"authorization": "Bearer secret"})
            assert requests == []
            state["fingerprint"] = hashlib.sha256(
                cert.public_bytes(serialization.Encoding.DER)
            ).hexdigest()
            assert (
                client.post(
                    url, content=b"private", headers={"authorization": "Bearer secret"}
                ).status_code
                == 200
            )
            assert requests == [("Bearer secret", b"private")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
