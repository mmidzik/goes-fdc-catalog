from goes_fdc import cli


def test_laps_report_each_phase(monkeypatch):
    clock = iter([10.0, 10.5, 13.0, 13.25])
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(clock))
    laps = cli.Laps()
    laps.lap("list")
    laps.lap("virtualize")
    laps.lap("commit")
    assert str(laps) == "list 0.5s, virtualize 2.5s, commit 0.2s"
