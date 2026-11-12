import json
import uuid
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.redis_bus import redis_bus
from app.core.security import decode_access_token
from app.db.session import get_session_factory
from app.models.game import Game, GameParticipant
from app.modules.auth.service import get_user_by_id
from app.modules.realtime.hub import ClientConnection, ws_hub
from app.modules.tournament.service import compute_clock_state

ws_router = APIRouter()


@ws_router.websocket("/ws/v1/games/{game_id}")
async def websocket_game_stream(
    websocket: WebSocket,
    game_id: uuid.UUID,
    token: str = Query(...),
    last_seq: int = Query(default=0),
) -> None:
    try:
        claims = decode_access_token(token)
        user_id = uuid.UUID(claims["sub"])
    except Exception:
        await websocket.close(code=4401)
        return

    factory = get_session_factory()
    async with factory() as session:
        try:
            user = await get_user_by_id(session, user_id)
        except Exception:
            await websocket.close(code=4401)
            return

        game = (await session.execute(select(Game).where(Game.id == game_id))).scalar_one_or_none()
        if game is None:
            await websocket.close(code=4404)
            return

        gp = (
            await session.execute(
                select(GameParticipant).where(
                    GameParticipant.game_id == game_id,
                    GameParticipant.user_id == user.id,
                )
            )
        ).scalar_one_or_none()
        clock = compute_clock_state(game)
        cur_seq = await redis_bus.current_game_seq(game_id)

    await websocket.accept()
    conn = ClientConnection(
        websocket=websocket,
        user_id=user.id,
        role=user.role,
        game_participant_id=gp.id if gp else None,
    )
    await ws_hub.register(game_id, conn)

    # Send immediate welcome & clock synchronization envelope
    await websocket.send_text(
        json.dumps(
            {
                "seq": cur_seq,
                "channel": "public:clock",
                "event": "WS_CONNECTED",
                "game_id": str(game_id),
                "server_ts": clock.server_ts.isoformat(),
                "game_elapsed_ms": clock.trading_elapsed_ms,
                "phase": game.status,
                "payload": {
                    "resync_recommended": (last_seq > 0 and last_seq < cur_seq),
                    "clock": clock.model_dump(mode="json"),
                },
            }
        )
    )

    try:
        while True:
            msg_text = await websocket.receive_text()
            try:
                data = json.loads(msg_text)
            except json.JSONDecodeError:
                continue
            if data.get("action") == "PING":
                await websocket.send_text(json.dumps({"event": "PONG", "ts": data.get("ts")}))
    except WebSocketDisconnect:
        pass
    finally:
        await ws_hub.unregister(game_id, conn)
