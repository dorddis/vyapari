"""Filename sanitization regression for image_store (P3.5b #6).

Pre-P3.5b:
  web_api.py:upload_image endpoint concatenated `uuid4().hex[:12] +
  "_" + file.filename` and passed it into services.image_store.upload_image.
  That service then did `full_path = _LOCAL_UPLOAD_DIR / f"{folder}/{fname}"`
  and `full_path.write_bytes(...)` with zero containment check.

  A multipart upload with `filename="../../src/router.py"` resolved
  outside the upload dir and overwrote source code. In dev (`APP_ENV=
  development` forces `_USE_SUPABASE=False`), this was always-on — RCE
  class.

Fix (layered):
  1. services.image_store._sanitize_path_segment strips anything
     outside `[A-Za-z0-9._-]` and leading dots; caps length.
  2. upload_image sanitizes both `filename` and `folder` BEFORE
     composing the path.
  3. _upload_local resolves the full path and asserts it sits inside
     _LOCAL_UPLOAD_DIR — final backstop against any future caller
     bypassing upload_image.
"""

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
    # Path separators MUST be stripped (they enable traversal). `..`
    # appearing between underscores in a single filename is harmless —
    # without a separator it resolves as one literal name.
    ("../../src/router.py",    ["src_router.py"], ["/", "\\"]),
    ("..\\..\\etc\\passwd",    ["etc_passwd"],    ["/", "\\"]),
    (".hidden",                 ["hidden"],        []),    # leading dot stripped
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
    """Leading dots (hidden files, `..`, `.`) must be stripped so the
    resulting name can never resolve as hidden or parent-dir."""
    for inp in [".hidden", "..secret", "...", "./foo"]:
        out = _sanitize_path_segment(inp)
        assert not out.startswith("."), (
            f"{inp!r} sanitized to {out!r} still starts with '.'"
        )


def test_sanitize_path_segment_empty_or_all_stripped_produces_fallback():
    """Entirely-bad inputs must produce a placeholder, not empty."""
    assert _sanitize_path_segment("") == "upload"
    assert _sanitize_path_segment("..") == "upload"   # "" after strip
    assert _sanitize_path_segment("...") == "upload"  # "" after strip


def test_sanitize_path_segment_caps_length():
    """Very long segments are capped to avoid FS path-length crashes."""
    out = _sanitize_path_segment("a" * 500)
    assert len(out) <= 64


def test_sanitize_preserves_extension_under_cap() -> None:
    """Mobile-export filenames like `IMG_..._long_export_filename.jpg`
    can exceed the 64-char cap. A naive `[:64]` would strip `.jpg`
    and the UI would render as application/octet-stream. Preserve the
    suffix."""
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
    "con.jpg", "Nul.txt", "AUX.pdf",  # case-insensitive stem match
])
def test_sanitize_handles_windows_reserved_names(name) -> None:
    """Win32 rejects reserved names even with an extension. Prefix with
    `_` so the file actually writes under Windows dev environments."""
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
    """Win32 silently trims trailing `.` and space, enabling collisions
    between `report.` and `report`. Strip them explicitly."""
    assert _sanitize_path_segment("report.") == "report"
    assert _sanitize_path_segment("photo  ") == "photo"
    assert _sanitize_path_segment("doc.pdf.") == "doc.pdf"


def test_sanitize_does_not_preserve_absurd_extension() -> None:
    """A 30-char "extension" on an over-cap filename is not a real
    extension — plain truncation is preferable to preserving it, because
    a 30-char suffix would leave only 34 chars for the stem and likely
    lose meaningful content."""
    # 50 + 1 + 30 = 81 chars total, above the 64 cap.
    out = _sanitize_path_segment("a" * 50 + "." + "x" * 30)
    assert len(out) <= 64
    # Must NOT end with the 30-char "ext" — our heuristic caps suffix at 16.
    assert not out.endswith("." + "x" * 30)


# ---------------------------------------------------------------------------
# upload_image (public API) — traversal neutralized in both layers
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_image_sanitizes_attacker_filename(tmp_path, monkeypatch):
    """A caller passing `filename='../../../src/router.py'` must land
    a file INSIDE the upload dir, not outside."""
    # Redirect uploads to a test-scoped dir so we can assert containment.
    import services.image_store as store
    monkeypatch.setattr(store, "_LOCAL_UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(store, "_USE_SUPABASE", False)

    await upload_image(
        image_bytes=b"attacker-controlled",
        filename="../../../src/router.py",
        folder="customer_uploads",
        content_type="image/jpeg",
    )

    # Assert: nothing written outside tmp_path (no `router.py` surfaced
    # in its "../../src/" relative location).
    outside = tmp_path.parent / "src" / "router.py"
    assert not outside.exists(), (
        f"Traversal succeeded — file written to {outside}"
    )

    # A file WAS written, and it's inside tmp_path.
    all_written = list(tmp_path.rglob("*"))
    assert any(p.is_file() for p in all_written), (
        "No file written at all"
    )
    for p in all_written:
        if p.is_file():
            # All written paths must be descendants of tmp_path (post-resolve).
            assert str(p.resolve()).startswith(str(tmp_path.resolve())), (
                f"{p} escapes tmp_path"
            )


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
    """Direct call to _upload_local with a pre-composed traversal path
    must refuse to write — defense in depth if future callers bypass
    upload_image's sanitization."""
    import services.image_store as store
    monkeypatch.setattr(store, "_LOCAL_UPLOAD_DIR", tmp_path)
    with pytest.raises(ValueError, match="resolves outside upload dir"):
        _upload_local(b"x", "../escape.txt")


def test_upload_local_accepts_in_tree_path(tmp_path, monkeypatch):
    """Normal in-tree path works."""
    import services.image_store as store
    monkeypatch.setattr(store, "_LOCAL_UPLOAD_DIR", tmp_path)
    monkeypatch.setattr("config.PUBLIC_BASE_URL", "http://test")
    url = _upload_local(b"hello", "sub/file.jpg")
    assert (tmp_path / "sub" / "file.jpg").read_bytes() == b"hello"
    assert url.endswith("/uploads/sub/file.jpg")
