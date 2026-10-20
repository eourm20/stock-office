"""Notification API: status without keys, subscribing only to known push services."""

from fastapi.testclient import TestClient


def test_subscribe_and_status_without_server_keys(client: TestClient) -> None:
    status = client.get("/api/v1/notify/status").json()
    assert status["enabled"] is False and status["public_key"] is None
    assert status["quiet"] == "23:00–07:00"
    keys = {"p256dh": "BPk", "auth": "xyz"}
    assert client.post("/api/v1/notify/subscribe",
                       json={"endpoint": "https://evil.example/p", "keys": keys}).status_code == 422
    ok = client.post("/api/v1/notify/subscribe",
                     json={"endpoint": "https://web.push.apple.com/abc", "keys": keys})
    assert ok.json() == {"subscriptions": 1}
    assert client.post("/api/v1/notify/test").status_code == 409  # no keys on this server
    gone = client.post("/api/v1/notify/unsubscribe",
                       json={"endpoint": "https://web.push.apple.com/abc"})
    assert gone.json() == {"subscriptions": 0}
