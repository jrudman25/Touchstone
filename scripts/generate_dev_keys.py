"""Generate an RS256 development keypair for JWT signing.

Writes an unencrypted PKCS8 private key and a SubjectPublicKeyInfo public key
to ``<repo>/.secrets/jwt`` by default. Refuses to overwrite existing files.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

PRIVATE_FILENAME = "private.pem"
PUBLIC_FILENAME = "public.pem"


def repo_root() -> Path:
    """Repository root, resolved from this file's location (not the cwd)."""
    return Path(__file__).resolve().parents[1]


def default_output_dir() -> Path:
    return repo_root() / ".secrets" / "jwt"


def _exclusive_write(path: Path, data: bytes, mode: int) -> None:
    """Write ``data`` to ``path``, failing if the file already exists.

    ``mode`` is applied by the OS at creation time on POSIX (subject to umask,
    so it can only become more restrictive); it has no effect on Windows ACLs.
    On any write or close failure the file this call created is removed;
    existing files are never touched.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(path, flags, mode)
    try:
        written = 0
        while written < len(data):
            n = os.write(fd, data[written:])
            if n == 0:
                raise OSError(f"zero-byte write to {path}")
            written += n
        os.close(fd)
    except BaseException:
        # The file was created by this call's O_EXCL, so removing it on
        # failure is safe and leaves no partial file behind.
        with contextlib.suppress(OSError):
            os.close(fd)
        path.unlink(missing_ok=True)
        raise


def generate_keypair(output_dir: Path) -> tuple[Path, Path]:
    """Create a new RSA-3072 keypair under ``output_dir``.

    Returns ``(private_path, public_path)``. Raises ``FileExistsError`` when
    either target already exists; existing files are never overwritten, and on
    a partial failure only files this call created are removed.
    """
    output_dir = Path(output_dir)
    private_path = output_dir / PRIVATE_FILENAME
    public_path = output_dir / PUBLIC_FILENAME

    existing = [str(p) for p in (private_path, public_path) if p.exists()]
    if existing:
        raise FileExistsError("refusing to overwrite existing key file(s): " + ", ".join(existing))

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_bytes = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    output_dir.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []
    try:
        _exclusive_write(private_path, private_bytes, 0o600)
        created.append(private_path)
        _exclusive_write(public_path, public_bytes, 0o644)
        created.append(public_path)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise

    return private_path, public_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate an RS256 development keypair for JWT signing."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=default_output_dir(),
        help="Directory for private.pem and public.pem (default: %(default)s).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        private_path, public_path = generate_keypair(args.output_dir)
    except FileExistsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"error: could not write keys: {exc}", file=sys.stderr)
        return 1
    print(f"private key: {private_path}")
    print(f"public key: {public_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
