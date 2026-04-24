import logging
from dataclasses import dataclass, field
from typing import Callable

from google.protobuf.internal.encoder import _VarintBytes  # type: ignore

from ankama_launcher_emulator.proxy.dofus3.login_message_pb2 import (
    IdentificationResponse,
    LoginMessage,
)
from ankama_launcher_emulator.proxy.dofus3.proxy import Proxy

logger = logging.getLogger()


def _encode_msg(msg: LoginMessage) -> bytes:
    content = msg.SerializeToString()
    return _VarintBytes(len(content)) + content


@dataclass
class ConnectionProxy(Proxy):
    on_game_connection_callback: Callable[[tuple[str, int]], int]
    on_shield_detected: Callable[[], None] | None = None
    on_session_expired: Callable[[], None] | None = None
    _auth_recovery_fired: bool = field(default=False, init=False)

    def alter_msg_datas(
        self, msg_content_datas: bytes, msg_datas: bytes
    ) -> bytes | None:
        msg = LoginMessage()
        msg.ParseFromString(msg_content_datas)

        if (
            not self._auth_recovery_fired
            and msg.response.HasField("identification")
            and msg.response.identification.HasField("error")
        ):
            reason = msg.response.identification.error.reason
            logger.warning(
                f"[DOFUS3_PROXY] Identification error reason={reason}"
            )
            if reason == IdentificationResponse.Error.INVALID_SHIELD_CERTIFICATE:
                self._auth_recovery_fired = True
                if self.on_shield_detected:
                    self.on_shield_detected()
            elif reason in (
                IdentificationResponse.Error.UNAUTHORIZED,
                IdentificationResponse.Error.UNKNOWN_AUTH_ERROR,
            ):
                self._auth_recovery_fired = True
                if self.on_session_expired:
                    self.on_session_expired()

        if msg.response.HasField("selectServer") and msg.response.selectServer.HasField(
            "success"
        ):
            new_port = self.on_game_connection_callback(
                (
                    msg.response.selectServer.success.host,
                    msg.response.selectServer.success.ports[0],
                )
            )
            msg.response.selectServer.success.host = "localhost"
            msg.response.selectServer.success.ports[0] = new_port
            return _encode_msg(msg)

        return msg_datas
