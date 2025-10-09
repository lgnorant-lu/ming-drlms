from __future__ import annotations

from typing import Callable, List, Optional

from ..state import Session


class RoomsViewModel:
    """协调房间相关组件之间的状态同步与事件广播"""

    def __init__(self, session: Session):
        self._session = session
        self._room_metadata_listeners: List[Callable[[Optional[str]], None]] = []
        self._current_room_listeners: List[
            Callable[[Optional[str], Optional[str]], None]
        ] = []
        self.current_room_id: Optional[str] = None
        self.current_room_name: Optional[str] = None

    # ------------------------------------------------------------------
    # 监听注册
    def add_room_metadata_listener(
        self, listener: Callable[[Optional[str]], None]
    ) -> Callable[[], None]:
        if listener not in self._room_metadata_listeners:
            self._room_metadata_listeners.append(listener)

        def unregister() -> None:
            if listener in self._room_metadata_listeners:
                self._room_metadata_listeners.remove(listener)

        return unregister

    def add_current_room_listener(
        self, listener: Callable[[Optional[str], Optional[str]], None]
    ) -> Callable[[], None]:
        if listener not in self._current_room_listeners:
            self._current_room_listeners.append(listener)

        def unregister() -> None:
            if listener in self._current_room_listeners:
                self._current_room_listeners.remove(listener)

        return unregister

    # ------------------------------------------------------------------
    # 状态广播
    def notify_room_metadata(self, room_name: Optional[str] = None) -> None:
        for listener in list(self._room_metadata_listeners):
            try:
                listener(room_name)
            except Exception:
                pass

    def set_current_room(
        self, room_id: Optional[str], room_name: Optional[str] = None
    ) -> None:
        display_name = room_name or room_id or ""
        current_display = (
            self.current_room_name or self.current_room_id or ""
        )
        if self.current_room_id == room_id and display_name == current_display:
            return

        canonical_room_id = room_id or ""
        self._session.set_current_room(canonical_room_id)
        self.current_room_id = room_id
        self.current_room_name = room_name or room_id

        for listener in list(self._current_room_listeners):
            try:
                listener(self.current_room_id, self.current_room_name)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Session 代理
    @property
    def session(self) -> Session:
        return self._session

