"""Install a CA-issued TLS certificate on a remote Tinyrooms deployment.

Usage:
    python tools/install_certificates.py <host> [rootdir] [-u USER]
        [--cert-dir DIR] [--cert FILE] [--key FILE] [--chain FILE ...]
        [--root FILE] [--server-name NAME ...] [--no-reload]

``host`` may be a bare hostname or ``user@host``; passwordless SSH and
passwordless sudo are required. The default root is ``~/tinyrooms`` and the
default certificate directory is ``.local/certificates``.

When paths are not supplied, the bundle is discovered by name: a
``*-certificate.crt`` (or ``.pem``) leaf, its ``*-key.key``, and optional
``*-intermediate.pem`` / ``*-cross.pem`` chain files. The leaf and chain are
installed as nginx's ``server.crt`` fullchain and the private key as
``server.key``. The previous pair and nginx site file are backed up under
``<rootdir>/nginx/backups/<timestamp>`` before nginx is refreshed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
for _path in (TOOLS_DIR, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from deploy import (  # noqa: E402
    ADMIN_SERVICE,
    SSH_OPTIONS,
    DeployError,
    read_services,
    remote_path,
    resolve_root,
    resolve_target,
    run_remote,
)
from server.mission_control.nginx_template import site_config  # noqa: E402

DEFAULT_ROOT = "~/tinyrooms"
DEFAULT_CERT_DIR = REPO_ROOT / ".local" / "certificates"
LEAF_SUFFIXES = ("-certificate.crt", "-certificate.pem")


class CertificateError(RuntimeError):
    """Raised when a local certificate bundle is missing or inconsistent."""


@dataclass(frozen=True)
class CertificateBundle:
    """Paths that make up one CA-issued certificate installation."""

    leaf: Path
    key: Path
    chain: tuple[Path, ...]
    root: Path | None = None


def openssl_bytes(*args: str) -> subprocess.CompletedProcess[bytes]:
    """Run openssl and return the completed process without raising."""

    return subprocess.run(["openssl", *args], capture_output=True, check=False)


def openssl_output(*args: str) -> bytes:
    """Run openssl and return stdout, raising CertificateError on failure."""

    result = openssl_bytes(*args)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CertificateError(f"openssl {' '.join(args)} failed: {detail}")
    return result.stdout


def parse_dns_names(output: str) -> list[str]:
    """Return DNS SAN values from ``openssl x509 -ext subjectAltName`` output."""

    return list(dict.fromkeys(re.findall(r"\bDNS:([A-Za-z0-9*._-]+)", output)))


def certificate_dns_names(cert: Path) -> list[str]:
    """Return the DNS names covered by a certificate."""

    result = openssl_bytes("x509", "-in", str(cert), "-noout", "-ext", "subjectAltName")
    names = parse_dns_names(result.stdout.decode("utf-8", errors="replace"))
    if names:
        return names
    subject = openssl_output("x509", "-in", str(cert), "-noout", "-subject", "-nameopt", "RFC2253")
    match = re.search(r"(?:^|[,=])CN=([^,\n]+)", subject.decode("utf-8", errors="replace"))
    return [match.group(1).strip()] if match else []


def certificate_matches_key(cert: Path, key: Path) -> bool:
    """Return whether the private key belongs to the certificate."""

    cert_public = openssl_bytes("x509", "-in", str(cert), "-pubkey", "-noout")
    key_public = openssl_bytes("pkey", "-in", str(key), "-pubout")
    return (
        cert_public.returncode == 0
        and key_public.returncode == 0
        and cert_public.stdout.strip() == key_public.stdout.strip()
    )


def merge_server_names(certificate_names: Sequence[str], extra_names: Sequence[str]) -> list[str]:
    """Return certificate DNS names followed by any additional names."""

    return list(dict.fromkeys([*certificate_names, *extra_names]))


def build_fullchain(bundle: CertificateBundle) -> bytes:
    """Return the leaf and intermediates as one newline-separated PEM bundle."""

    parts: list[bytes] = []
    for path in (bundle.leaf, *bundle.chain):
        data = path.read_bytes().strip()
        if not data.startswith(b"-----BEGIN CERTIFICATE-----") or b"-----END CERTIFICATE-----" not in data:
            raise CertificateError(f"{path} does not contain a PEM certificate")
        parts.append(data)
    return b"\n".join(parts) + b"\n"


def _find_bundle_file(directories: Sequence[Path], candidates: Sequence[str]) -> Path | None:
    for directory in dict.fromkeys(directories):
        for candidate in candidates:
            path = directory / candidate
            if path.is_file():
                return path
    return None


def discover_bundle(
    cert_dir: Path,
    *,
    cert: Path | None = None,
    key: Path | None = None,
    chain: Sequence[Path] = (),
    root: Path | None = None,
) -> CertificateBundle:
    """Discover or normalize a certificate bundle from local paths."""

    cert_dir = cert_dir.expanduser()
    if cert is None:
        leaves = sorted(cert_dir.glob("*-certificate.crt")) or sorted(cert_dir.glob("*-certificate.pem"))
        if not leaves:
            raise CertificateError(
                f"no *-certificate.crt or *-certificate.pem file found in {cert_dir}; pass --cert and --key"
            )
        if len(leaves) > 1:
            names = ", ".join(path.name for path in leaves)
            raise CertificateError(f"multiple certificate leaves found in {cert_dir}: {names}; pass --cert")
        cert = leaves[0]
    cert = cert.expanduser()
    if not cert.is_file():
        raise CertificateError(f"certificate not found: {cert}")

    base = cert.name
    for suffix in LEAF_SUFFIXES:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    else:
        base = cert.stem

    search_dirs = list(dict.fromkeys((cert.parent, cert_dir)))
    if key is None:
        key = _find_bundle_file(
            search_dirs,
            (f"{base}-key.key", f"{base}-key.pem", f"{base}.key"),
        )
        if key is None:
            keys = [path for directory in search_dirs for path in sorted(directory.glob("*.key"))]
            if len(keys) == 1:
                key = keys[0]
    if key is None:
        raise CertificateError(f"no private key found for {cert.name} in {cert_dir}; pass --key")
    key = key.expanduser()
    if not key.is_file():
        raise CertificateError(f"private key not found: {key}")

    if chain:
        chain_paths = tuple(path.expanduser() for path in chain)
    else:
        discovered = [
            _find_bundle_file(search_dirs, (name,))
            for name in (f"{base}-intermediate.pem", f"{base}-cross.pem")
        ]
        chain_paths = tuple(path for path in discovered if path is not None)
    for path in chain_paths:
        if not path.is_file():
            raise CertificateError(f"chain certificate not found: {path}")

    if root is None:
        candidate = _find_bundle_file(search_dirs, (f"{base}-root.pem",))
        root = candidate
    elif not root.expanduser().is_file():
        raise CertificateError(f"root certificate not found: {root}")
    else:
        root = root.expanduser()

    return CertificateBundle(leaf=cert, key=key, chain=chain_paths, root=root)


def validate_bundle(bundle: CertificateBundle) -> list[str]:
    """Validate the local certificate/key/chain and return its DNS names."""

    if not certificate_matches_key(bundle.leaf, bundle.key):
        raise CertificateError(f"{bundle.key} does not match the public key in {bundle.leaf}")
    if openssl_bytes("x509", "-in", str(bundle.leaf), "-noout", "-checkend", "0").returncode != 0:
        raise CertificateError(f"{bundle.leaf} is expired or not yet valid")

    for path in bundle.chain:
        if openssl_bytes("x509", "-in", str(path), "-noout").returncode != 0:
            raise CertificateError(f"{path} is not a valid PEM certificate")

    if bundle.root is not None:
        verify_args = ["verify", "-CAfile", str(bundle.root)]
        if bundle.chain:
            with TemporaryDirectory() as temp_dir:
                chain_path = Path(temp_dir) / "chain.pem"
                chain_path.write_bytes(b"\n".join(path.read_bytes().strip() for path in bundle.chain) + b"\n")
                result = openssl_bytes(*verify_args, "-untrusted", str(chain_path), str(bundle.leaf))
        else:
            result = openssl_bytes(*verify_args, str(bundle.leaf))
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise CertificateError(f"certificate chain does not verify against {bundle.root}: {detail}")

    names = certificate_dns_names(bundle.leaf)
    if not names:
        raise CertificateError(f"{bundle.leaf} has no DNS subject alternative name")
    return names


def upload_bytes(host: str, remote_file: str, data: bytes) -> None:
    """Write bytes to a remote file over SSH."""

    result = subprocess.run(
        ["ssh", *SSH_OPTIONS, host, f"cat > {remote_file}"],
        input=data,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise DeployError(f"Could not upload {remote_file}: {detail}")


def _validate_server_names(names: Sequence[str]) -> None:
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9*._-]+", name):
            raise CertificateError(f"invalid nginx server name: {name!r}")


def _rollback(host: str, root: str, backup_dir: str) -> None:
    cert = remote_path(root, "nginx", "certs", "server.crt")
    key = remote_path(root, "nginx", "certs", "server.key")
    cert_staging = remote_path(root, "nginx", "certs", "server.crt.new")
    key_staging = remote_path(root, "nginx", "certs", "server.key.new")
    run_remote(
        host,
        "set +e; "
        f"if [ -f {backup_dir}/server.crt ]; then cp -p {backup_dir}/server.crt {cert}; else rm -f {cert}; fi; "
        f"if [ -f {backup_dir}/server.key ]; then cp -p {backup_dir}/server.key {key}; else rm -f {key}; fi; "
        f"if [ -f {backup_dir}/tinyrooms.conf ]; then "
        "sudo -n cp "
        f"{backup_dir}/tinyrooms.conf /etc/nginx/sites-available/tinyrooms; fi; "
        f"rm -f {cert_staging} {key_staging}; "
        "sudo -n nginx -t >/dev/null 2>&1 && sudo -n systemctl reload nginx >/dev/null 2>&1; true",
        check=False,
    )


def install_bundle(
    host: str,
    root: str,
    bundle: CertificateBundle,
    server_names: Sequence[str],
    *,
    reload: bool = True,
) -> str:
    """Install and validate the certificate on the remote host.

    Returns the remote backup directory.
    """

    _validate_server_names(server_names)
    registry = read_services(host, root)
    entry = registry.get(ADMIN_SERVICE)
    if not entry or not entry.get("port"):
        raise DeployError(f"no {ADMIN_SERVICE} service is registered under {root}; deploy the host first")
    port = int(entry["port"])  # type: ignore[arg-type]

    base = root.rstrip("/")
    cert = remote_path(root, "nginx", "certs", "server.crt")
    key = remote_path(root, "nginx", "certs", "server.key")
    cert_staging = remote_path(root, "nginx", "certs", "server.crt.new")
    key_staging = remote_path(root, "nginx", "certs", "server.key.new")
    config_home = remote_path(root, "nginx", "tinyrooms.conf")
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_dir = remote_path(root, "nginx", "backups", timestamp)

    run_remote(host, f"mkdir -p {remote_path(root, 'nginx', 'certs')} {backup_dir}")
    upload_bytes(host, cert_staging, build_fullchain(bundle))
    upload_bytes(host, key_staging, bundle.key.read_bytes())
    run_remote(host, f"chmod 600 {cert_staging} {key_staging}")
    run_remote(
        host,
        "set -e; "
        f'test "$(openssl x509 -in {cert_staging} -pubkey -noout)" = '
        f'"$(openssl pkey -in {key_staging} -pubout)"; '
        f"openssl x509 -in {cert_staging} -noout -checkend 0 >/dev/null; "
        f"if [ -f {cert} ]; then cp -p {cert} {backup_dir}/server.crt; fi; "
        f"if [ -f {key} ]; then cp -p {key} {backup_dir}/server.key; fi; "
        "if sudo -n test -f /etc/nginx/sites-available/tinyrooms; then "
        f"sudo -n cat /etc/nginx/sites-available/tinyrooms > {backup_dir}/tinyrooms.conf; fi",
    )

    config = site_config(
        server_name=" ".join(server_names),
        cert_path=f"{base}/nginx/certs/server.crt",
        key_path=f"{base}/nginx/certs/server.key",
        port=port,
    )
    try:
        run_remote(host, f"mv -f {cert_staging} {cert} && mv -f {key_staging} {key}")
        upload_bytes(host, config_home, config.encode("utf-8"))
        run_remote(
            host,
            f"sudo -n cp {config_home} /etc/nginx/sites-available/tinyrooms && "
            "sudo -n ln -sfn /etc/nginx/sites-available/tinyrooms /etc/nginx/sites-enabled/tinyrooms && "
            "sudo -n rm -f /etc/nginx/sites-enabled/default && "
            "sudo -n nginx -t",
        )
        if reload:
            run_remote(host, "sudo -n systemctl reload nginx || sudo -n systemctl start nginx")
    except DeployError:
        _rollback(host, root, backup_dir)
        raise
    return f"{base}/nginx/backups/{timestamp}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description="Install a CA-issued TLS certificate on a Tinyrooms host.")
    parser.add_argument("host", help="Remote hostname or user@hostname (passwordless SSH access required).")
    parser.add_argument("rootdir", nargs="?", default=DEFAULT_ROOT, help=f"Deployment root (default: {DEFAULT_ROOT}).")
    parser.add_argument("-u", "--user", help="SSH user; overrides any user embedded in the host argument.")
    parser.add_argument("--cert-dir", type=Path, default=DEFAULT_CERT_DIR, help=f"Certificate bundle directory (default: {DEFAULT_CERT_DIR}).")
    parser.add_argument("--cert", type=Path, help="Leaf certificate file (default: discovered *-certificate.crt).")
    parser.add_argument("--key", type=Path, help="Private key file (default: discovered *-key.key).")
    parser.add_argument("--chain", type=Path, action="append", default=[], help="Intermediate certificate to append; may repeat.")
    parser.add_argument("--root", type=Path, help="Root CA used only to verify the local chain.")
    parser.add_argument(
        "--server-name",
        action="append",
        default=[],
        help="Additional nginx server_name besides the certificate DNS SANs; may repeat.",
    )
    parser.add_argument("--no-reload", action="store_true", help="Install and test the configuration without reloading nginx.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Install a certificate bundle on the remote host."""

    args = parse_args(argv)
    try:
        ssh_target, _ = resolve_target(args.host, args.user)
        root = resolve_root(ssh_target, args.rootdir)
        bundle = discover_bundle(
            args.cert_dir,
            cert=args.cert,
            key=args.key,
            chain=args.chain,
            root=args.root,
        )
        certificate_names = validate_bundle(bundle)
        server_names = merge_server_names(certificate_names, args.server_name)
        backup_dir = install_bundle(ssh_target, root, bundle, server_names, reload=not args.no_reload)
    except (CertificateError, DeployError) as exc:
        print(f"install-certificates: {exc}", file=sys.stderr)
        return 1

    print(f"Installed {bundle.leaf.name} on {ssh_target}:{root}")
    print(f"  certificate names: {', '.join(certificate_names)}")
    print(f"  nginx server_name: {', '.join(server_names)}")
    print(f"  backup: {backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
