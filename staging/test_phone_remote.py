from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

from source_1_3_101.pigeon_poker.phone_remote import (
    PHONE_HTML,
    PhoneRemoteServer,
    build_phone_snapshot,
)


def _request(url: str, *, method: str = "GET", body=None, token: str = ""):
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read().decode("utf-8")) if "json" in response.headers.get("Content-Type", "") else response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception:
            value = raw
        return exc.code, value


def test_phone_snapshot_never_exposes_opponent_hole_cards() -> None:
    result = build_phone_snapshot([{
        "id": "table-1",
        "players": [
            {"name": "YOU", "stack_cents": 12345, "is_hero": True, "hole_cards": ["As", "Ah"]},
            {"name": "CPU", "stack_cents": 10000, "hole_cards": ["Kd", "Kc"], "private_strategy": "secret"},
        ],
        "hero_hole_cards": ["As", "Ah"],
        "board": ["2c", "3d", "4h"],
        "hidden_cpu_cards": ["Kd", "Kc"],
    }])
    encoded = json.dumps(result)
    assert "Kd" not in encoded
    assert "private_strategy" not in encoded
    assert "hidden_cpu_cards" not in encoded
    assert result["tables"][0]["hero_hole_cards"] == ["As", "Ah"]
    assert "hole_cards" not in result["tables"][0]["players"][1]


def test_phone_remote_requires_pairing_and_accepts_authenticated_actions() -> None:
    received = []
    ready = threading.Event()

    def enqueue(action):
        received.append(action)
        ready.set()
        return True

    server = PhoneRemoteServer(enqueue, host="127.0.0.1", port=0)
    server.start()
    try:
        url = server.urls[0]
        status, _ = _request(url.rstrip("/") + "/api/state")
        assert status == 401

        status, paired = _request(
            url.rstrip("/") + "/api/pair",
            method="POST",
            body={"code": server.pairing_code},
        )
        assert status == 200 and paired.get("token")
        token = paired["token"]

        server.publish_state(build_phone_snapshot([{
            "id": "t1", "rate": "NL10", "status": "YOUR TURN",
            "actions": ["fold", "call"], "hero_turn": True,
        }], wallet_cents=12300))
        status, snapshot = _request(url.rstrip("/") + "/api/state", token=token)
        assert status == 200
        assert snapshot["wallet_cents"] == 12300
        assert snapshot["tables"][0]["id"] == "t1"

        status, accepted = _request(
            url.rstrip("/") + "/api/action",
            method="POST",
            token=token,
            body={"table_id": "t1", "action": "call"},
        )
        assert status == 202 and accepted["accepted"] is True
        assert ready.wait(1.0)
        assert received == [{"table_id": "t1", "action": "call", "amount_cents": None}]

        status, _ = _request(
            url.rstrip("/") + "/api/action",
            method="POST",
            body={"table_id": "t1", "action": "all-in"},
        )
        assert status == 401
    finally:
        server.stop()


def test_phone_remote_rejects_invalid_commands_and_bet_amounts() -> None:
    received = []
    server = PhoneRemoteServer(lambda item: received.append(item) or True, host="127.0.0.1", port=0)
    server.start()
    try:
        url = server.urls[0].rstrip("/")
        status, paired = _request(url + "/api/pair", method="POST", body={"code": server.pairing_code})
        assert status == 200
        token = paired["token"]
        status, _ = _request(url + "/api/action", method="POST", token=token,
                             body={"table_id": "t1", "action": "shutdown"})
        assert status == 400
        status, _ = _request(url + "/api/action", method="POST", token=token,
                             body={"table_id": "t1", "action": "bet", "amount_cents": "100"})
        assert status == 400
        assert received == []
    finally:
        server.stop()


def test_phone_remote_page_contains_mobile_controls_and_no_external_assets() -> None:
    assert "viewport" in PHONE_HTML
    assert "PAIR PHONE" in PHONE_HTML
    assert "FOLD" in PHONE_HTML
    assert "CHECK" in PHONE_HTML
    assert "CALL" in PHONE_HTML
    assert "ALL-IN" in PHONE_HTML
    assert "submitBet" in PHONE_HTML
    assert "https://" not in PHONE_HTML
    assert "localStorage" not in PHONE_HTML


def run_tests() -> None:
    tests = [
        test_phone_snapshot_never_exposes_opponent_hole_cards,
        test_phone_remote_requires_pairing_and_accepts_authenticated_actions,
        test_phone_remote_rejects_invalid_commands_and_bet_amounts,
        test_phone_remote_page_contains_mobile_controls_and_no_external_assets,
    ]
    for test in tests:
        test()
        print("PASS", test.__name__)
    print("ALL PASS", len(tests), "phone remote tests")


if __name__ == "__main__":
    run_tests()
