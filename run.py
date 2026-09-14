"""HTTPS launcher for the Tinyrooms Milestone 1 backend."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from pathlib import Path
import argparse
import os
import signal
import socket
import threading
from types import FrameType

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import uvicorn

from server.app import create_app
from server.config import ConfigError, load_config


GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS = 1
FORCED_EXIT_TIMEOUT_SECONDS = 1.9


class BoundedShutdownServer(uvicorn.Server):
    """Give connections time to close, then guarantee that the process exits."""

    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self._shutdown_complete = threading.Event()
        self._shutdown_watchdog: threading.Thread | None = None

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        if self._shutdown_watchdog is None:
            self._shutdown_watchdog = threading.Thread(
                target=self._force_exit_after_timeout,
                args=(sig,),
                name="tinyrooms-shutdown-watchdog",
                daemon=True,
            )
            self._shutdown_watchdog.start()
        super().handle_exit(sig, frame)

    def _force_exit_after_timeout(self, sig: int) -> None:
        if not self._shutdown_complete.wait(FORCED_EXIT_TIMEOUT_SECONDS):
            os._exit(128 + sig)

    def run(self, sockets: list[socket.socket] | None = None) -> None:
        try:
            super().run(sockets=sockets)
        finally:
            self._shutdown_complete.set()


def _cert_paths(local_path: Path) -> tuple[Path, Path]:
    return local_path / "cert.pem", local_path / "key.pem"


def _load_certificate(cert_path: Path) -> x509.Certificate | None:
    if not cert_path.is_file():
        return None
    return x509.load_pem_x509_certificate(cert_path.read_bytes())


def ensure_self_signed_certificate(local_path: Path, host: str) -> tuple[Path, Path]:
    """Create or reuse a self-signed development certificate."""

    cert_path, key_path = _cert_paths(local_path)
    certificate = _load_certificate(cert_path)
    if certificate is not None and certificate.not_valid_after_utc > datetime.now(tz=UTC) + timedelta(days=1):
        if key_path.is_file():
            return cert_path, key_path
    local_path.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    common_name = "Tinyrooms Development"
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(tz=UTC) - timedelta(minutes=5))
        .not_valid_after(datetime.now(tz=UTC) + timedelta(days=14))
    )
    alt_names: list[x509.GeneralName] = [x509.DNSName("localhost")]
    for value in {host, "127.0.0.1"}:
        try:
            alt_names.append(x509.IPAddress(ip_address(value)))
        except ValueError:
            if value not in {"0.0.0.0", "::"}:
                alt_names.append(x509.DNSName(value))
    certificate = builder.add_extension(x509.SubjectAlternativeName(alt_names), critical=False).sign(key, hashes.SHA256())
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def parse_args() -> argparse.Namespace:
    """Parse optional launcher arguments."""

    parser = argparse.ArgumentParser(description="Run the Tinyrooms Milestone 1 backend.")
    parser.add_argument("--host", help="Override TRSERVER_HOST for this run.")
    parser.add_argument("--port", type=int, help="Override TRSERVER_PORT for this run.")
    parser.add_argument("--certfile", help="Use an existing PEM certificate file.")
    parser.add_argument("--keyfile", help="Use an existing PEM key file.")
    return parser.parse_args()


def main() -> int:
    """Run the HTTPS development server."""

    args = parse_args()
    try:
        env_values = dict(os.environ)
        if args.host:
            env_values["TRSERVER_HOST"] = args.host
        if args.port:
            env_values["TRSERVER_PORT"] = str(args.port)
        config = load_config(env=env_values)
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    if args.certfile and args.keyfile:
        cert_path = Path(args.certfile)
        key_path = Path(args.keyfile)
    else:
        cert_path, key_path = ensure_self_signed_certificate(config.local_path, config.host)
    server = BoundedShutdownServer(uvicorn.Config(
        create_app(config),
        host=config.host,
        port=config.port,
        ssl_certfile=str(cert_path),
        ssl_keyfile=str(key_path),
        log_level="info",
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS,
    ))
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
