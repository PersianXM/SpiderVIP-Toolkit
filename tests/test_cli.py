import json

from spidervip.cli import main


def test_cli_diagnose_simulated(capsys):
    rc = main(["diagnose", "--simulate", "--fault", "player-crash"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "NO picture" in out and "NO sound" in out
    assert "decoder service is not running" in out


def test_cli_repair_fixes_and_exits_zero(capsys):
    rc = main(["repair", "--simulate", "--fault", "player-crash"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Final A/V status: picture OK, sound OK" in out


def test_cli_repair_json_output(capsys):
    rc = main(["repair", "--simulate", "--fault", "demux-stuck", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["fixed"] is True
    assert payload["steps"][0]["patch"] == "reinit-demux"


def test_cli_repair_unfixable_exits_nonzero(capsys):
    rc = main(["repair", "--simulate", "--fault", "weak-signal"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "manual attention" in out


def test_cli_faults_lists_all(capsys):
    rc = main(["faults"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "player-crash" in out
