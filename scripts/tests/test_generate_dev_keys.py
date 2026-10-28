"""Tests for scripts/generate_dev_keys.py using real temp directories."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from generate_dev_keys import (
    PRIVATE_FILENAME,
    PUBLIC_FILENAME,
    build_parser,
    default_output_dir,
    generate_keypair,
    main,
    repo_root,
)

OTHER = {PRIVATE_FILENAME: PUBLIC_FILENAME, PUBLIC_FILENAME: PRIVATE_FILENAME}


def _load_private(path: Path) -> RSAPrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    assert isinstance(key, RSAPrivateKey)
    return key


def _load_public(path: Path) -> RSAPublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    assert isinstance(key, RSAPublicKey)
    return key


def _assert_valid_keypair(directory: Path) -> None:
    private_key = _load_private(directory / PRIVATE_FILENAME)
    public_key = _load_public(directory / PUBLIC_FILENAME)
    assert private_key.key_size == 3072
    assert private_key.public_key().public_numbers().e == 65537

    message = b"touchstone-dev-keypair"
    signature = private_key.sign(message, padding.PKCS1v15(), hashes.SHA256())
    public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())


def _track_opened_fds(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, str]]:
    """Patch os.open to record (fd, path) pairs while performing real opens."""
    real_open = os.open
    opened: list[tuple[int, str]] = []

    def tracking_open(
        path: str | os.PathLike[str],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        opened.append((fd, str(path)))
        return fd

    monkeypatch.setattr(os, "open", tracking_open)
    return opened


def test_generated_keypair_is_matching_rsa3072(tmp_path: Path) -> None:
    private_path, public_path = generate_keypair(tmp_path)
    assert private_path == tmp_path / PRIVATE_FILENAME
    assert public_path == tmp_path / PUBLIC_FILENAME
    _assert_valid_keypair(tmp_path)


def test_main_creates_keys_in_output_dir(tmp_path: Path) -> None:
    assert main(["--output-dir", str(tmp_path)]) == 0
    assert (tmp_path / PRIVATE_FILENAME).is_file()
    assert (tmp_path / PUBLIC_FILENAME).is_file()


def test_default_output_dir_is_repo_secrets() -> None:
    expected = repo_root() / ".secrets" / "jwt"
    assert default_output_dir() == expected
    assert build_parser().parse_args([]).output_dir == expected


@pytest.mark.parametrize("which", [PRIVATE_FILENAME, PUBLIC_FILENAME])
def test_existing_file_is_preserved_and_no_counterpart(tmp_path: Path, which: str) -> None:
    sentinel = b"sentinel-original"
    target = tmp_path / which
    target.write_bytes(sentinel)

    assert main(["--output-dir", str(tmp_path)]) == 1
    assert target.read_bytes() == sentinel
    assert not (tmp_path / OTHER[which]).exists()


def test_second_run_fails_and_preserves_both(tmp_path: Path) -> None:
    assert main(["--output-dir", str(tmp_path)]) == 0
    private_before = (tmp_path / PRIVATE_FILENAME).read_bytes()
    public_before = (tmp_path / PUBLIC_FILENAME).read_bytes()

    assert main(["--output-dir", str(tmp_path)]) == 1
    assert (tmp_path / PRIVATE_FILENAME).read_bytes() == private_before
    assert (tmp_path / PUBLIC_FILENAME).read_bytes() == public_before


def test_short_writes_still_produce_valid_keypair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A filesystem that accepts only a few bytes per write still yields a
    complete, parseable, matching keypair."""
    opened = _track_opened_fds(monkeypatch)
    real_write = os.write

    def chunked_write(fd: int, data: bytes) -> int:
        if any(fd == tracked for tracked, _ in opened):
            return real_write(fd, data[:8])
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", chunked_write)

    assert generate_keypair(tmp_path) == (
        tmp_path / PRIVATE_FILENAME,
        tmp_path / PUBLIC_FILENAME,
    )
    _assert_valid_keypair(tmp_path)


def test_private_write_failure_leaves_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure mid-write on the private key removes its partial file and
    never creates the public key."""
    opened = _track_opened_fds(monkeypatch)
    real_write = os.write
    calls = 0

    def flaky_write(fd: int, data: bytes) -> int:
        nonlocal calls
        if not any(fd == tracked for tracked, _ in opened):
            return real_write(fd, data)
        calls += 1
        if calls > 1:
            raise OSError("simulated write failure")
        return real_write(fd, data[:4])

    monkeypatch.setattr(os, "write", flaky_write)

    assert main(["--output-dir", str(tmp_path)]) == 1
    assert not (tmp_path / PRIVATE_FILENAME).exists()
    assert not (tmp_path / PUBLIC_FILENAME).exists()


def test_public_write_failure_leaves_no_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure mid-write on the public key removes both its partial file
    and the already-written private key."""
    opened = _track_opened_fds(monkeypatch)
    real_write = os.write
    calls = 0

    def flaky_write(fd: int, data: bytes) -> int:
        nonlocal calls
        public_fds = [tracked for tracked, p in opened if p.endswith(PUBLIC_FILENAME)]
        if fd not in public_fds:
            return real_write(fd, data)
        calls += 1
        if calls > 1:
            raise OSError("simulated write failure")
        return real_write(fd, data[:4])

    monkeypatch.setattr(os, "write", flaky_write)

    assert main(["--output-dir", str(tmp_path)]) == 1
    assert not (tmp_path / PRIVATE_FILENAME).exists()
    assert not (tmp_path / PUBLIC_FILENAME).exists()


def test_secret_paths_are_git_ignored() -> None:
    """.env and generated key paths are ignored; uv.lock is not."""
    root = repo_root()
    for rel in (".env", ".secrets/jwt/private.pem", ".secrets/jwt/public.pem"):
        result = subprocess.run(["git", "check-ignore", "-q", rel], cwd=root)
        assert result.returncode == 0, f"{rel} must be git-ignored"
    result = subprocess.run(["git", "check-ignore", "-q", "uv.lock"], cwd=root)
    assert result.returncode == 1, "uv.lock must not be git-ignored"
