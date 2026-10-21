import json

from vlog_skill import cli


def test_cli_envelope_and_exit_codes(tmp_path, capsys):
    assert cli.main(["init", str(tmp_path / "proj"), "--topic", "demo"]) == 0
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] and env["command"] == "init" and "edit" in env["data"]["created"]

    assert cli.main(["utterances", str(tmp_path / "missing.json")]) == cli.EXIT_INPUT
    env = json.loads(capsys.readouterr().out)
    assert not env["ok"] and env["error"]["type"] == "FileNotFoundError"

    assert cli.main(["nonsense"]) == cli.EXIT_USAGE
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "UsageError"


def test_cli_ffmpeg_failure_is_tool_error(tmp_path, capsys):
    bad = tmp_path / "not_audio.wav"
    bad.write_text("not audio")
    assert cli.main(["quiet", str(bad), "--start", "0", "--end", "1"]) == cli.EXIT_TOOL
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "ToolError"


def test_heygen_is_not_a_command(capsys):
    assert cli.main(["heygen", "me"]) == cli.EXIT_USAGE
    capsys.readouterr()
