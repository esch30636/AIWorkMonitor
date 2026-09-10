from aiworkmonitor.relay import ConnectionRegistry


async def test_registry_keeps_latest_telemetry() -> None:
    registry = ConnectionRegistry()
    await registry.update_device("pc-1", "hello", {"name": "Main PC"})
    await registry.update_device("pc-1", "telemetry", {"cpu": {"usagePercent": 42}})
    snapshot = await registry.snapshot()
    assert snapshot["devices"][0]["name"] == "Main PC"
    assert snapshot["devices"][0]["telemetry"]["cpu"]["usagePercent"] == 42


async def test_registry_caps_activity_history() -> None:
    registry = ConnectionRegistry()
    for index in range(120):
        await registry.update_device("pc-1", "activity", {"text": str(index)})
    snapshot = await registry.snapshot()
    activity = snapshot["devices"][0]["activity"]
    assert len(activity) == 100
    assert activity[0]["text"] == "20"

