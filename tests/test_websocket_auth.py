"""Transport authentication must precede commands, interrupts and telemetry."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect


@pytest.fixture
def client(monkeypatch):
    import main
    monkeypatch.setattr(main, "API_TOKEN", "test-websocket-token")
    monkeypatch.setattr(main.task_manager, "submit_task", AsyncMock())
    monkeypatch.setattr(main.task_manager, "interrupt_current", AsyncMock())
    return TestClient(main.app)


@pytest.mark.parametrize("path", ["/ws/agent", "/ws/telemetry"])
@pytest.mark.parametrize("message", [
    {"type": "authenticate", "token": "wrong"},
    {"type": "command", "text": "open notepad"},
    {"type": "interrupt"},
    {"type": "authenticate", "token": []},
    [],
])
def test_unauthorized_frames_are_closed_before_work(client, path, message):
    import main
    with client.websocket_connect(path) as socket:
        socket.send_json(message)
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_json()
        assert error.value.code == 1008
    main.task_manager.submit_task.assert_not_awaited()
    main.task_manager.interrupt_current.assert_not_awaited()


@pytest.mark.parametrize("path", ["/ws/agent", "/ws/telemetry"])
@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost:5173.evil.example"])
def test_foreign_browser_origins_rejected_even_with_token(client, path, origin):
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(path, headers={"origin": origin}):
            pass
    assert error.value.code == 1008


@pytest.mark.parametrize("origin", [None, "http://localhost:5173", "http://127.0.0.1:5173"])
def test_valid_client_can_authenticate_and_submit(client, origin):
    import main
    headers = {"origin": origin} if origin else {}
    with client.websocket_connect("/ws/agent", headers=headers) as socket:
        socket.send_json({"type": "authenticate", "token": "test-websocket-token"})
        assert socket.receive_json() == {"type": "authenticated"}
        socket.send_json({"type": "command", "text": "hello"})
        socket.send_json({"type": "interrupt"})
        assert socket.receive_json()["type"] == "interrupted"
        main.task_manager.submit_task.assert_awaited_once()
        main.task_manager.interrupt_current.assert_awaited_once()


def test_malformed_handshake_closed(client):
    with client.websocket_connect("/ws/agent") as socket:
        socket.send_text("not JSON")
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_json()
        assert error.value.code == 1008


def test_handshake_timeout_fails_closed(monkeypatch):
    import main
    import asyncio
    socket = AsyncMock()
    socket.headers = {}
    async def timed_out(awaitable, timeout):
        awaitable.close()
        raise TimeoutError
    monkeypatch.setattr(main.asyncio, "wait_for", timed_out)
    assert asyncio.run(main.authenticate_websocket(socket)) is False
    socket.close.assert_awaited_once_with(code=1008)
    socket.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_non_ascii_bearer_is_rejected_without_server_error():
    import main
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        await main.require_api_token("Bearer \u2603")
    assert error.value.status_code == 401
