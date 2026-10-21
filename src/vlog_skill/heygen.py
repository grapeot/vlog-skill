"""A thin standard-library client for the HeyGen v3 API: own avatar, own audio, download.

Implemented against the documented v3 API (researched 2026-10-20). It has not yet been exercised
with a real key; treat the first real run as the test. v1 and v2 are not supported.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib import error, parse, request

from .audio import DependencyError

BASE_URL = "https://api.heygen.com"
SIMPLE_UPLOAD_MAX_BYTES = 32 * 1024 * 1024
TERMINAL = {"completed", "failed"}
# HeyGen accepts MP3 and WAV for audio; convert anything else (for example M4A) first.
AUDIO_TYPES = {".wav": "audio/wav", ".mp3": "audio/mpeg"}
NETWORK_ERRORS = (error.URLError, OSError, http.client.HTTPException)


class UpstreamError(RuntimeError):
    """HeyGen answered with an error; carries the raw status and body."""

    def __init__(self, status: int | None, body: str, url: str):
        super().__init__(f"HeyGen request failed ({status}) for {url}: {body[:500]}")
        self.status = status
        self.body = body
        self.url = url


def _from_env_file(path: Path) -> str | None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if line.startswith("HEYGEN_API_KEY="):
            value = line.split("=", 1)[1].strip()
            if value[:1] in "\"'" and value[:1] and value.count(value[0]) >= 2:
                return value[1:value.index(value[0], 1)]
            return value.split(" #", 1)[0].strip()
    return None


def api_key(env_file: str | Path | None = ".env") -> str:
    key = os.environ.get("HEYGEN_API_KEY")
    if not key and env_file and Path(env_file).is_file():
        key = _from_env_file(Path(env_file))
    key = (key or "").strip()
    if not key:
        raise DependencyError("HEYGEN_API_KEY is not set (environment or .env)")
    if not re.fullmatch(r"[\x21-\x7e]+", key):  # never echo the value itself
        raise DependencyError("HEYGEN_API_KEY contains whitespace or non-printable characters")
    return key


class Client:
    def __init__(self, key: str, base_url: str = BASE_URL, timeout_s: float = 120.0, opener=None):
        self.key = key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._open = opener or request.urlopen

    def _call(self, method: str, path: str, body: dict | None = None, data: bytes | None = None,
              headers: dict | None = None, query: dict | None = None) -> dict:
        url = self.base_url + path + (("?" + parse.urlencode(query)) if query else "")
        hdrs = {"X-Api-Key": self.key, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        req = request.Request(url, data=data, method=method, headers=hdrs)
        try:
            with self._open(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except error.HTTPError as exc:
            raise UpstreamError(exc.code, exc.read().decode("utf-8", errors="replace"), url) from exc
        except NETWORK_ERRORS as exc:
            raise UpstreamError(None, f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}", url) from exc
        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise UpstreamError(200, raw, url) from exc

    @staticmethod
    def _data(resp: dict) -> dict:
        data = resp.get("data", resp) if isinstance(resp, dict) else resp
        return data if isinstance(data, dict) else {}

    def me(self) -> dict:
        return self._call("GET", "/v3/users/me")

    def looks(self, avatar_type: str = "digital_twin", ownership: str = "private", limit: int = 50) -> dict:
        return self._call("GET", "/v3/avatars/looks", query={"avatar_type": avatar_type, "ownership": ownership, "limit": limit})

    def upload(self, path: str | Path) -> dict:
        """Upload an audio file and return the response whose data carries asset_id."""
        path = Path(path)
        ctype = AUDIO_TYPES.get(path.suffix.lower())
        if ctype is None:
            raise ValueError(f"HeyGen accepts WAV or MP3 audio, not {path.suffix or 'this file'}; "
                             "convert first, e.g. ffmpeg -i in.m4a -b:a 192k out.mp3")
        size = path.stat().st_size
        if size <= SIMPLE_UPLOAD_MAX_BYTES:
            boundary = uuid.uuid4().hex
            payload = (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
                f"Content-Type: {ctype}\r\n\r\n"
            ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
            return self._call("POST", "/v3/assets", data=payload,
                              headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        start = self._call("POST", "/v3/assets/direct-uploads",
                           body={"filename": path.name, "content_type": ctype, "size_bytes": size})
        info = self._data(start)
        headers = dict(info.get("upload_headers") or {})
        # urllib would otherwise add application/x-www-form-urlencoded, which can break a signed URL
        if not any(h.lower() == "content-type" for h in headers):
            headers["Content-Type"] = ctype
        put = request.Request(info["upload_url"], data=path.read_bytes(), method="PUT", headers=headers)
        try:
            with self._open(put, timeout=max(self.timeout_s, 1800)) as resp:
                resp.read()
        except error.HTTPError as exc:
            raise UpstreamError(exc.code, exc.read().decode("utf-8", errors="replace"), "upload_url") from exc
        except NETWORK_ERRORS as exc:
            raise UpstreamError(None, f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}", "upload_url") from exc
        done = self._call("POST", f"/v3/assets/{info['asset_id']}/complete", body={})
        if not isinstance(done.get("data"), dict):
            done["data"] = {}
        done["data"].setdefault("asset_id", info["asset_id"])
        return done

    def create(self, avatar_id: str, audio_asset_id: str | None = None, audio_url: str | None = None,
               engine: str | None = None, resolution: str | None = None, aspect_ratio: str | None = None,
               output_format: str | None = None, title: str | None = None, callback_url: str | None = None,
               idempotency_key: str | None = None) -> dict:
        if bool(audio_asset_id) == bool(audio_url):
            raise ValueError("give exactly one of audio_asset_id or audio_url")
        body: dict = {"type": "avatar", "avatar_id": avatar_id}
        if audio_asset_id:
            body["audio_asset_id"] = audio_asset_id
        if audio_url:
            body["audio_url"] = audio_url
        if engine:
            body["engine"] = {"type": engine}
        for k, v in (("resolution", resolution), ("aspect_ratio", aspect_ratio), ("output_format", output_format),
                     ("title", title), ("callback_url", callback_url)):
            if v:
                body[k] = v
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._call("POST", "/v3/videos", body=body, headers=headers)

    def status(self, video_id: str) -> dict:
        return self._call("GET", f"/v3/videos/{video_id}")

    def wait(self, video_id: str, timeout_s: float = 7200, interval_s: float = 30, sleep=time.sleep) -> dict:
        """Poll until completed or failed. Unknown non-terminal states (for example 'waiting') count as running."""
        deadline = time.monotonic() + timeout_s
        while True:
            resp = self.status(video_id)
            if str(self._data(resp).get("status", "")).lower() in TERMINAL:
                return resp
            if time.monotonic() >= deadline:
                raise TimeoutError(f"video {video_id} still running after {timeout_s} s: {self._data(resp).get('status')}")
            sleep(interval_s)

    def download(self, video_id: str, out: str | Path) -> dict:
        """Fetch a fresh presigned URL and save the video. Returns the status response used."""
        resp = self.status(video_id)
        data = self._data(resp)
        if str(data.get("status", "")).lower() != "completed" or not data.get("video_url"):
            raise ValueError(f"video {video_id} is not ready: status={data.get('status')}")
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".part")
        try:
            with self._open(request.Request(data["video_url"]), timeout=max(self.timeout_s, 1800)) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
        except error.HTTPError as exc:
            raise UpstreamError(exc.code, exc.read().decode("utf-8", errors="replace"), "video_url") from exc
        except NETWORK_ERRORS as exc:
            raise UpstreamError(None, f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}", "video_url") from exc
        tmp.replace(out)
        return resp
