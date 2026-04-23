"""Filename sanitization regression for image_store."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.image_store import (
    _LOCAL_UPLOAD_DIR,
    _sanitize_path_segment,
    _upload_local,
    upload_image,
)


# ---------------------------------------------------------------------------
# _sanitize_path_segment — unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected_contains,expected_excludes", [
    ("../../src/router.py",    ["src_router.py"], ["/", "\\"]),
    ("..\\..\\etc\\passwd",    ["etc_passwd"],    ["/", "\\"]),
    (".hidden",                 ["hidden"],        []),
    ("normal.jpg",              ["normal.jpg"],    []),
    ("with spaces and %@!.jpg", ["with_spaces_and____.jpg"], [" ", "%", "@", "!"]),
    ("///passwd",               ["passwd"],        ["/"]),
    ("\x00null.exe",            ["null.exe"],      ["\x00"]),
])
def test_sanitize_path_segment(raw, expected_contains, expected_excludes):
    out = _sanitize_path_segment(raw)
    for s in expected_contains:
        assert s in out, f"{s!r} not in sanitized {out!r} (input {raw!r})"
    for s in expected_excludes:
        assert s not in out, f"{s!r} survived sanitization of {raw!r} -> {out!r}"


def test_sanitize_path_segment_does_not_start_with_dot() -> None:
    """Leading dots are stripped."""
    for inp in [".hidden", "..secret", "...", "./foo"]:
        out = _sanitize_path_segment(inp)
        assert not out.startswith("."), (
            f"{inp!r} sanitized to {out!r} still starts with '.'"
        )


def test_sanitize_path_segment_empty_or_all_stripped_produces_fallback():
    """All-bad input produces 'upload' placeholder."""
    assert _sanitize_path_segment("") == "upload"
    assert _sanitize_path_segment("..") == "upload"
    assert _sanitize_path_segment("...") == "upload"


def test_sanitize_path_segment_caps_length():
    """Very long segments are capped."""
    out = _sanitize_path_segment("a" * 500)
    assert len(out) <= 64


def test_sanitize_preserves_extension_under_cap() -> None:
    """Truncation preserves a short final extension."""
    long_with_ext = "a" * 80 + ".jpg"
    out = _sanitize_path_segment(long_with_ext)
    assert len(out) <= 64
    assert out.endswith(".jpg"), f"Extension lost in {out!r}"


def test_sanitize_preserves_reasonable_extensions() -> None:
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".pdf"):
        out = _sanitize_path_segment("x" * 90 + ext)
        assert out.endswith(ext), f"Lost {ext} -> {out}"


@pytest.mark.parametrize("name", [
    "CON", "PRN", "AUX", "NUL",
    "COM1", "LPT1", "COM9", "LPT9",
    "con.jpg", "Nul.txt", "AUX.pdf",
])
def test_sanitize_handles_windows_reserved_names(name) -> None:
    """Win32 reserved stems are prefixed with `_` so writes don't fail."""
    out = _sanitize_path_segment(name)
    # The resulting stem (pre-extension) must NOT be a reserved name.
    from pathlib import PurePath
    stem = PurePath(out).stem
    assert stem.upper() not in {
        "CON", "PRN", "AUX", "NUL",
        "COM1","COM2","COM3","COM4","COM5","COM6","COM7","COM8","COM9",
        "LPT1","LPT2","LPT3","LPT4","LPT5","LPT6","LPT7","LPT8","LPT9",
    }, f"{name!r} -> {out!r} still resolves to reserved stem {stem!r}"


def test_sanitize_strips_trailing_dot_and_space() -> None:
    """Trailing `.` and space are stripped (Win32 would silent-trim them)."""
    assert _sanitize_path_segment("report.") == "report"
    assert _sanitize_path_segment("photo  ") == "photo"
    assert _sanitize_path_segment("doc.pdf.") == "doc.pdf"


def test_sanitize_does_not_preserve_absurd_extension() -> None:
    """Extensions longer than 16 chars are not treated as extensions."""
    out = _sanitize_path_segment("a" * 50 + "." + "x" * 30)
    assert len(out) <= 64
    assert not out.endswith("." + "x" * 30)


# ---------------------------------------------------------------------------
# upload_image (public API) — traversal neutralized in both layers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_image_sanitizes_attacker_filename(tmp_path, monkeypatch):
    """`filename='../../../src/router.py'` stays inside the upload dir."""
    import services.image_store as store
    monkeypatch.setattr(store, "_LOCAL_UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(store, "_USE_SUPABASE", False)

    await upload_image(
        image_bytes=b"attacker-controlled",
        filename="../../../src/router.py",
        folder="customer_uploads",
        content_type="image/jpeg",
    )

    outside = tmp_path.parent / "src" / "router.py"
    assert not outside.exists(), f"Traversal escaped to {outside}"

    all_written = list(tmp_path.rglob("*"))
    assert any(p.is_file() for p in all_written)
    for p in all_written:
        if p.is_file():
            assert str(p.resolve()).startswith(str(tmp_path.resolve()))


@pytest.mark.asyncio
async def test_upload_image_sanitizes_attacker_folder(tmp_path, monkeypatch):
    """Same check but with `folder='../'` instead of filename."""
    import services.image_store as store
    monkeypatch.setattr(store, "_LOCAL_UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(store, "_USE_SUPABASE", False)

    await upload_image(
        image_bytes=b"x",
        filename="safe.jpg",
        folder="../../../etc",
        content_type="image/jpeg",
    )

    outside = tmp_path.parent.parent.parent / "etc" / "safe.jpg"
    assert not outside.exists()


# ---------------------------------------------------------------------------
# _upload_local — backstop containment check (final defense)
# ---------------------------------------------------------------------------

def test_upload_local_rejects_escaping_path(tmp_path, monkeypatch):
    """Backstop: _upload_local refuses a pre-composed traversal path."""
    import services.image_store as store
    monkeypatch.setattr(store, "_LOCAL_UPLOAD_DIR", tmp_path)
    with pytest.raises(ValueError, match="resolves outside upload dir"):
        _upload_local(b"x", "../escape.txt")


def test_upload_local_accepts_in_tree_path(tmp_path, monkeypatch):
    """In-tree path writes and returns a URL."""
    import services.image_store as store
    monkeypatch.setattr(store, "_LOCAL_UPLOAD_DIR", tmp_path)
    monkeypatch.setattr("config.PUBLIC_BASE_URL", "http://test")
    url = _upload_local(b"hello", "sub/file.jpg")
    assert (tmp_path / "sub" / "file.jpg").read_bytes() == b"hello"
    assert url.endswith("/uploads/sub/file.jpg")
