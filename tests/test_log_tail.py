import json

from aiworkmonitor.providers.log_tail import JsonlTail


def test_jsonl_tail_does_not_replay_existing_conversation(tmp_path) -> None:
    log = tmp_path / "session.jsonl"
    log.write_text(json.dumps({"type": "message", "message": {"role": "assistant", "content": "old"}}) + "\n")
    tail = JsonlTail(str(tmp_path / "*.jsonl"))

    assert tail.poll() == []

    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"type": "message", "message": {"role": "assistant", "content": "new"}}) + "\n")

    events = tail.poll()
    assert [event["text"] for event in events] == ["new"]
