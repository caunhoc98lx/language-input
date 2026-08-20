"""Private file storage for uploaded IELTS material.

Files never live under a web-served directory and are never named by anything
the uploader controls: the key is derived from the content hash, so path
traversal and filename collisions are impossible by construction.

ponytail: local disk, not S3. `save`/`open_file`/`delete` are the whole
interface - point them at boto3/Supabase when this runs on more than one
machine. The DB only ever stores the key, so nothing else has to change.
"""
import hashlib
import os
import shutil
import zipfile
from pathlib import Path

STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "storage")).resolve()
MAX_PDF_BYTES = int(os.environ.get("MAX_PDF_MB", "100")) * 1024 * 1024
MAX_AUDIO_BYTES = int(os.environ.get("MAX_AUDIO_MB", "200")) * 1024 * 1024
MAX_ZIP_MEMBERS = int(os.environ.get("MAX_ZIP_MEMBERS", "60"))


class UploadError(ValueError):
    """Rejected upload - the message is safe to show the user."""


# Extensions are a hint for the error message only; the magic bytes decide.
_AUDIO_MIME = {"mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav"}


def sniff(data: bytes) -> tuple[str, str, str] | None:
    """(kind, mime, extension) from the file's own bytes, or None if unknown."""
    if data[:5] == b"%PDF-":
        return "PDF", "application/pdf", "pdf"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "AUDIO", "audio/mpeg", "mp3"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "AUDIO", "audio/wav", "wav"
    if data[4:8] == b"ftyp":
        return "AUDIO", "audio/mp4", "m4a"
    if data[:4] == b"PK\x03\x04":
        return "ZIP", "application/zip", "zip"
    return None


def validate(data: bytes, filename: str) -> tuple[str, str, str]:
    """Check type and size. Raises UploadError with a user-facing message."""
    if not data:
        raise UploadError(f"{filename} is empty.")
    sniffed = sniff(data)
    if not sniffed:
        raise UploadError(
            f"{filename} is not a PDF, MP3, M4A, WAV or ZIP file "
            "(checked the file contents, not the extension)."
        )
    kind, mime, ext = sniffed
    limit = MAX_PDF_BYTES if kind == "PDF" else MAX_AUDIO_BYTES
    if len(data) > limit:
        raise UploadError(f"{filename} is {len(data) // 1024 // 1024} MB; the limit is {limit // 1024 // 1024} MB.")
    return kind, mime, ext


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def save(user_id: int, data: bytes, ext: str) -> str:
    """Write bytes to private storage, return the storage key.

    Content-addressed, so re-uploading the same file overwrites itself rather
    than filling the disk with duplicates.
    """
    digest = sha256(data)
    key = f"{user_id}/{digest[:2]}/{digest}.{ext}"
    path = _path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)  # atomic: a reader never sees a half-written file
    return key


def _path(key: str) -> Path:
    path = (STORAGE_DIR / key).resolve()
    if not path.is_relative_to(STORAGE_DIR):
        raise UploadError("Invalid storage key.")
    return path


def open_file(key: str):
    return _path(key).open("rb")


def local_path(key: str) -> str:
    """Filesystem path - only for tools that need a real file (PDF rendering)."""
    return str(_path(key))


def exists(key: str) -> bool:
    return _path(key).exists()


def delete(key: str) -> None:
    _path(key).unlink(missing_ok=True)


def unpack_zip(data: bytes) -> list[tuple[str, bytes]]:
    """Return [(name, bytes)] for the audio files inside a zip.

    Member names are used for audio matching later, so they are returned - but
    only the basename, and only after the member has been read into memory, so
    a "../../etc/passwd" entry can never reach the filesystem.
    """
    out: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(_BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir() or len(out) >= MAX_ZIP_MEMBERS:
                continue
            if info.file_size > MAX_AUDIO_BYTES:
                continue
            member = zf.read(info)
            if sniff(member) and sniff(member)[0] == "AUDIO":
                out.append((os.path.basename(info.filename.replace("\\", "/")), member))
    return out


from io import BytesIO as _BytesIO  # noqa: E402  (used above, imported late to keep the header tidy)


def _demo():
    import tempfile
    global STORAGE_DIR
    original = STORAGE_DIR
    STORAGE_DIR = Path(tempfile.mkdtemp()).resolve()
    try:
        # Type detection reads the bytes, so a mislabelled file is caught.
        assert sniff(b"%PDF-1.7\n...")[0] == "PDF"
        assert sniff(b"ID3\x03..." + b"\x00" * 20)[0] == "AUDIO"
        assert sniff(b"RIFF\x00\x00\x00\x00WAVEfmt ")[1] == "audio/wav"
        assert sniff(b"\x00\x00\x00\x20ftypM4A ")[2] == "m4a"
        assert sniff(b"PK\x03\x04rest")[0] == "ZIP"
        assert sniff(b"hello world") is None

        try:
            validate(b"<html>not a pdf</html>", "test.pdf")
            raise AssertionError("a .pdf extension must not be enough")
        except UploadError as e:
            assert "not a PDF" in str(e)
        try:
            validate(b"", "empty.pdf")
            raise AssertionError("empty file must be rejected")
        except UploadError:
            pass

        # Oversized files are rejected before anything is written.
        global MAX_PDF_BYTES
        old_limit, MAX_PDF_BYTES = MAX_PDF_BYTES, 10
        try:
            validate(b"%PDF-" + b"x" * 100, "big.pdf")
            raise AssertionError("oversized file must be rejected")
        except UploadError as e:
            assert "limit is" in str(e)
        finally:
            MAX_PDF_BYTES = old_limit

        # Round-trip, and identical content de-duplicates to one key.
        data = b"%PDF-1.7 hello"
        key = save(7, data, "pdf")
        assert key == save(7, data, "pdf")
        assert save(8, data, "pdf") != key, "different users get different keys"
        assert open_file(key).read() == data
        assert exists(key) and key.startswith("7/")

        # Storage keys can never escape the storage root.
        for evil in ("../../secret.pdf", "/etc/passwd", "7/../../../x.pdf"):
            try:
                _path(evil)
                raise AssertionError(f"path traversal not blocked: {evil}")
            except UploadError:
                pass

        # Zip extraction keeps only audio members, and flattens hostile names.
        buf = _BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("audio/../../evil.mp3", b"ID3\x03" + b"\x00" * 30)
            zf.writestr("notes.txt", b"just text")
        members = unpack_zip(buf.getvalue())
        assert [name for name, _ in members] == ["evil.mp3"], members

        delete(key)
        assert not exists(key)
        print("storage self-check OK")
    finally:
        shutil.rmtree(STORAGE_DIR, ignore_errors=True)
        STORAGE_DIR = original


if __name__ == "__main__":
    _demo()
