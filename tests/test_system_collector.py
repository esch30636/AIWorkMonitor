from aiworkmonitor.collectors.system import SystemCollector


def test_system_collector_returns_portable_shape() -> None:
    sample = SystemCollector().sample()
    assert 0 <= sample["cpu"]["usagePercent"] <= 100
    assert sample["memory"]["usedBytes"] > 0
    assert sample["memory"]["totalBytes"] >= sample["memory"]["usedBytes"]
    assert isinstance(sample["gpus"], list)

