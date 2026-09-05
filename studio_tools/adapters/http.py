"""Bounded HTTPS with deliberately quiet failures and atomic downloads."""

import json
from pathlib import Path
import struct
import urllib.error
import urllib.parse
import urllib.request
from ..common import StudioError


class ProviderError(StudioError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Transport:
    def __init__(self, timeout=60, max_bytes=256 * 1024 * 1024):
        self.timeout = timeout
        self.max_bytes = max_bytes

    def request(self, method, url, headers=None, body=None, binary=False):
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ProviderError("Provider URLs must use HTTPS")
        req = urllib.request.Request(
            url,
            data=json.dumps(body, allow_nan=False).encode()
            if body is not None
            else None,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                chunks = []
                size = 0
                while True:
                    chunk = response.read(min(1024 * 1024, self.max_bytes - size + 1))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise ProviderError(
                            "Provider response exceeded configured byte limit"
                        )
                    chunks.append(chunk)
                data = b"".join(chunks)
                declared = response.headers.get("Content-Length")
                if declared and len(data) != int(declared):
                    raise ProviderError(
                        "Incomplete provider response; output not accepted"
                    )
                meta = {
                    k: response.headers[k]
                    for k in (
                        "request-id",
                        "x-request-id",
                        "character-cost",
                        "content-type",
                    )
                    if k in response.headers
                }
                return (data, meta) if binary else json.loads(data)
        except ProviderError:
            raise
        except urllib.error.HTTPError as exc:
            raise ProviderError(
                f"Provider HTTP {exc.code}; inspect account/parameters without logging credentials",
                exc.code,
            ) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise ProviderError(
                "Provider response unavailable or invalid; a submitted request may have been received"
            ) from None

    def download(self, url, destination):
        path = Path(destination)
        partial = path.with_suffix(path.suffix + ".part")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data, _ = self.request("GET", url, binary=True)
            partial.write_bytes(data)
            validate_download(partial, path.suffix)
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)


def validate_download(path, suffix):
    data = Path(path).read_bytes()
    if not data:
        raise ProviderError("Empty downloaded asset")
    suffix = suffix.lower()
    if suffix == ".glb":
        if (
            len(data) < 20
            or data[:4] != b"glTF"
            or struct.unpack_from("<I", data, 4)[0] != 2
            or struct.unpack_from("<I", data, 8)[0] != len(data)
        ):
            raise ProviderError("Downloaded GLB is incomplete or invalid")
    elif suffix == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ProviderError("Downloaded PNG is invalid")
    elif suffix in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8"):
        raise ProviderError("Downloaded JPEG is invalid")
    elif suffix == ".mp3" and not (
        data.startswith(b"ID3")
        or (len(data) > 1 and data[0] == 255 and data[1] & 224 == 224)
    ):
        raise ProviderError("Downloaded MP3 is invalid")
    elif data.lstrip().startswith((b"<html", b"<!DOCTYPE", b'{"error')):
        raise ProviderError("Downloaded file is an error document")
