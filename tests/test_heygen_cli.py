import io
import json
from urllib import error

import pytest

from vlog_skill import cli
from vlog_skill.audio import DependencyError
from vlog_skill.heygen import Client, UpstreamError, api_key


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Recorder:
    """Stands in for urllib.request.urlopen and serves canned responses in order."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return FakeResp(r if isinstance(r, bytes) else json.dumps(r).encode())


def test_create_sends_documented_v3_body_and_idempotency_key():
    rec = Recorder([{"data": {"video_id": "v1", "status": "pending"}}])
    c = Client("k", opener=rec)
    out = c.create("look1", audio_asset_id="a1", engine="avatar_iv", output_format="webm", idempotency_key="idem")
    req = rec.requests[0]
    assert req.full_url == "https://api.heygen.com/v3/videos" and req.get_method() == "POST"
    assert json.loads(req.data) == {"type": "avatar", "avatar_id": "look1", "audio_asset_id": "a1",
                                    "engine": {"type": "avatar_iv"}, "output_format": "webm"}
    assert req.headers["X-api-key"] == "k" and req.headers["Idempotency-key"] == "idem"
    assert out["data"]["video_id"] == "v1"
    with pytest.raises(ValueError):
        c.create("look1")


def test_small_audio_uses_multipart_upload(tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"ID3fake")
    rec = Recorder([{"data": {"asset_id": "as1"}}])
    out = Client("k", opener=rec).upload(f)
    req = rec.requests[0]
    assert req.full_url.endswith("/v3/assets") and b'name="file"; filename="a.mp3"' in req.data
    assert out["data"]["asset_id"] == "as1"


def test_large_audio_uses_direct_upload(tmp_path, monkeypatch):
    import vlog_skill.heygen as hg

    monkeypatch.setattr(hg, "SIMPLE_UPLOAD_MAX_BYTES", 4)
    f = tmp_path / "a.wav"
    f.write_bytes(b"RIFFdata")
    rec = Recorder([
        {"data": {"asset_id": "as2", "upload_url": "https://upload.example/x", "upload_headers": {"Content-Type": "audio/wav"}}},
        b"",
        {"data": {}},
    ])
    out = Client("k", opener=rec).upload(f)
    assert [r.get_method() for r in rec.requests] == ["POST", "PUT", "POST"]
    assert json.loads(rec.requests[0].data) == {"filename": "a.wav", "content_type": "audio/wav", "size_bytes": 8}
    assert rec.requests[1].full_url == "https://upload.example/x" and rec.requests[1].data == b"RIFFdata"
    assert rec.requests[2].full_url.endswith("/v3/assets/as2/complete")
    assert out["data"]["asset_id"] == "as2"


def test_wait_treats_unknown_states_as_running():
    rec = Recorder([{"data": {"status": "waiting"}}, {"data": {"status": "processing"}}, {"data": {"status": "completed", "video_url": "u"}}])
    out = Client("k", opener=rec).wait("v1", timeout_s=60, interval_s=0, sleep=lambda s: None)
    assert out["data"]["status"] == "completed" and len(rec.requests) == 3


def test_download_streams_fresh_url(tmp_path):
    rec = Recorder([{"data": {"status": "completed", "video_url": "https://cdn.example/v.mp4"}}, b"MP4BYTES"])
    Client("k", opener=rec).download("v1", tmp_path / "avatar" / "avatar.mp4")
    assert (tmp_path / "avatar" / "avatar.mp4").read_bytes() == b"MP4BYTES"
    assert not (tmp_path / "avatar" / "avatar.mp4.part").exists()


def test_http_error_body_passes_through():
    err = error.HTTPError("https://api.heygen.com/v3/videos", 403, "Forbidden", {}, io.BytesIO(b'{"error":{"code":"api_key_required"}}'))
    with pytest.raises(UpstreamError) as exc:
        Client("k", opener=Recorder([err])).status("v1")
    assert exc.value.status == 403 and "api_key_required" in exc.value.body


def test_api_key_from_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OTHER=1\nHEYGEN_API_KEY='secret'\n")
    assert api_key(tmp_path / ".env") == "secret"
    with pytest.raises(DependencyError):
        api_key(tmp_path / "missing.env")


def test_cli_envelope_and_exit_codes(tmp_path, capsys, monkeypatch):
    assert cli.main(["init", str(tmp_path / "proj"), "--topic", "demo"]) == 0
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] and env["command"] == "init" and "edit" in env["data"]["created"]

    assert cli.main(["utterances", str(tmp_path / "missing.json")]) == cli.EXIT_INPUT
    env = json.loads(capsys.readouterr().out)
    assert not env["ok"] and env["error"]["type"] == "FileNotFoundError"

    assert cli.main(["nonsense"]) == cli.EXIT_USAGE
    capsys.readouterr()

    monkeypatch.delenv("HEYGEN_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["heygen", "me"]) == cli.EXIT_DEPENDENCY
    env = json.loads(capsys.readouterr().out)
    assert env["command"] == "heygen me" and "HEYGEN_API_KEY" in env["error"]["message"]


def test_cli_wait_failed_render_is_upstream_error(capsys, monkeypatch):
    import vlog_skill.heygen as hg

    monkeypatch.setenv("HEYGEN_API_KEY", "k")
    rec = Recorder([{"data": {"status": "failed", "failure_code": "x"}}])
    monkeypatch.setattr(hg.request, "urlopen", rec)
    assert cli.main(["heygen", "wait", "v1", "--interval", "0"]) == cli.EXIT_UPSTREAM
    env = json.loads(capsys.readouterr().out)
    assert env["error"]["type"] == "UpstreamError" and "failure_code" in env["error"]["details"]["body"]


def test_cli_ffmpeg_failure_is_upstream_error(tmp_path, capsys):
    bad = tmp_path / "not_audio.wav"
    bad.write_text("not audio")
    assert cli.main(["quiet", str(bad), "--start", "0", "--end", "1"]) == cli.EXIT_UPSTREAM
    env = json.loads(capsys.readouterr().out)
    assert env["error"]["type"] == "ToolError"
