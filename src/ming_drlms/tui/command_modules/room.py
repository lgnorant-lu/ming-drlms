from __future__ import annotations

from typing import Any
from textual.widgets import Label, ListView as _ListView
from ..widgets import MessageList
from ...cli.mproto_runtime import create_mp2_client


def register_room_commands(handler: Any) -> None:
    def _rooms(args: str) -> None:
        service = handler._room_service()
        token_path = handler._token_store_path()
        try:
            rooms, _, _ = service.list_rooms(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                token_store_path=token_path,
            )
            if not rooms:
                handler.screen.show_system_message("(no rooms)")
                return
            lines = [" Rooms:"]
            for r in rooms:
                if hasattr(r, "room_name"):
                    name = r.room_name
                elif hasattr(r, "name"):
                    name = r.name
                else:
                    name = str(r)
                prefix = "" if name == handler.screen.current_room else "-"
                lines.append(f"  {prefix} {name}")
            handler.screen.show_system_message("\n".join(lines))
        except Exception as e:
            handler.screen.show_system_message(f" /rooms failed: {e}")

    def _join(args: str) -> None:
        room = args.strip()
        if not room:
            handler.screen.show_system_message("Usage: /join <room_name>")
            return
        # Scheme A: enforce atomicity — only join existing rooms.
        # Pre-check existence via fetch_info; do not implicitly create by subscribe.
        try:
            service = handler._room_service()
            token_path = handler._token_store_path()
            # If fetch_info fails (e.g., 404), treat as non-existent and refuse join.
            service.fetch_info(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                room=room,
                token_store_path=token_path,
            )
        except Exception as e:
            msg = str(e)
            low = msg.lower()
            if "404" in low or "not found" in low:
                handler.screen.show_system_message(
                    f" Room '{room}' does not exist. Use /create-room {room} first."
                )
            else:
                handler.screen.show_system_message(f" Failed to join room {room}: {e}")
            return

        handler.screen.current_room = room
        try:
            try:
                handler.screen.query_one("#chat-header", Label).update(f"~ {room} ~")
            except Exception:
                pass

            try:
                handler.screen.query_one(MessageList).clear()
            except Exception:
                pass

            handler.screen._connect_to_room(room)  # type: ignore[attr-defined]
            handler.screen.app.run_worker(
                lambda: handler.screen._refresh_members(room),  # type: ignore[attr-defined]
                thread=True,
            )
            handler.screen.show_system_message(f" Switched to room: {room}")
        except Exception as e:
            handler.screen.show_system_message(f" Failed to join room {room}: {e}")

    def _create_room(args: str) -> None:
        parts = args.split()
        if not parts:
            handler.screen.show_system_message(
                "Usage: /create-room <name> [policy=persistent|ephemeral]"
            )
            return
        room = parts[0]
        policy = parts[1] if len(parts) > 1 else "persistent"

        service = handler._room_service()
        token_path = handler._token_store_path()
        try:
            service.create_room(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                room=room,
                policy=policy,
                token_store_path=token_path,
            )
            handler.screen.show_system_message(
                f" Created room '{room}' with policy '{policy}'."
            )
        except Exception as e:
            handler.screen.show_system_message(f" /create-room failed: {e}")

    def _room_info(args: str) -> None:
        room = args.strip() or handler.screen.current_room
        service = handler._room_service()
        token_path = handler._token_store_path()
        try:
            info = service.fetch_info(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                room=room,
                token_store_path=token_path,
            )
            d = info.details
            lines = [f" Room info for '{room}':"]
            owner = d.get("owner")
            if owner is not None:
                lines.append(f"  owner: {owner}")
            subs = d.get("subscribers") or d.get("total_subscribers")
            if subs is not None:
                lines.append(f"  subscribers: {subs}")
            storage = d.get("storage_policy_name") or d.get("storage_policy")
            if storage is not None:
                lines.append(f"  storage: {storage}")
            last_event = d.get("last_event_id")
            if last_event is not None:
                lines.append(f"  last_event_id: {last_event}")
            handler.screen.show_system_message("\n".join(lines))
        except Exception as e:
            handler.screen.show_system_message(f" /room-info failed: {e}")

    def _members(args: str) -> None:
        room = args.strip() or handler.screen.current_room
        service = handler._room_service()
        token_path = handler._token_store_path()
        try:
            members = service.get_room_members_mp2(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                room=room,
                token_store_path=token_path,
            )
            if not members:
                handler.screen.show_system_message(f" No members in room '{room}'.")
                return
            lines = [f" Members in '{room}':"]
            for m in members:
                name = getattr(m, "user_id", None) or str(m)
                lines.append(f"  - {name}")
            handler.screen.show_system_message("\n".join(lines))
        except Exception as e:
            handler.screen.show_system_message(f" /members failed: {e}")

    def _leave(args: str) -> None:
        target = args.strip() or handler.screen.current_room
        if not target:
            handler.screen.show_system_message("Usage: /leave [room_name]")
            return
        try:
            if target == handler.screen.current_room:
                # Disconnect subscription to current room
                handler.controller.disconnect()
                handler.screen.show_system_message(f" Left room: {target}")
                # Clear member list to reflect disconnected state
                try:
                    handler.screen.query_one("#member-list", _ListView).clear()
                except Exception:
                    pass
                handler.screen.show_system_message(
                    "You are not connected to any room. Use /join <room> to connect."
                )
            else:
                handler.screen.show_system_message(
                    f" Not connected to {target}; nothing to leave."
                )
        except Exception as e:
            handler.screen.show_system_message(f" /leave failed: {e}")

    def _set_policy(args: str) -> None:
        parts = args.split()
        if len(parts) < 2:
            handler.screen.show_system_message(
                "Usage: /set-policy <room> <retain|delegate|teardown>"
            )
            return
        room, policy = parts[0], parts[1]
        service = handler._room_service()
        token_path = handler._token_store_path()
        try:
            service.set_policy(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                room=room,
                policy=policy,
                token_store_path=token_path,
            )
            handler.screen.show_system_message(
                f" Policy set to {policy} for room '{room}'"
            )
        except Exception as e:
            handler.screen.show_system_message(f" /set-policy failed: {e}")

    def _set_storage(args: str) -> None:
        parts = args.split()
        if len(parts) < 2:
            handler.screen.show_system_message(
                "Usage: /set-storage <room> <persistent|ephemeral>"
            )
            return
        room, policy = parts[0], parts[1]
        service = handler._room_service()
        token_path = handler._token_store_path()
        try:
            service.set_storage_policy(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                room=room,
                policy=policy,
                token_store_path=token_path,
            )
            handler.screen.show_system_message(
                f" Storage policy set to {policy} for room '{room}'"
            )
        except Exception as e:
            handler.screen.show_system_message(f" /set-storage failed: {e}")

    def _transfer_owner(args: str) -> None:
        parts = args.split()
        if len(parts) < 2:
            handler.screen.show_system_message("Usage: /transfer-owner <room> <user>")
            return
        room, new_owner = parts[0], parts[1]
        service = handler._room_service()
        token_path = handler._token_store_path()
        try:
            service.transfer_owner(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                room=room,
                new_owner=new_owner,
                token_store_path=token_path,
            )
            handler.screen.show_system_message(
                f" Ownership transferred to {new_owner} for room '{room}'"
            )
        except Exception as e:
            handler.screen.show_system_message(f" /transfer-owner failed: {e}")

    def _clear_owner(args: str) -> None:
        room = args.strip() or handler.screen.current_room
        if not room:
            handler.screen.show_system_message("Usage: /clear-owner <room>")
            return
        service = handler._room_service()
        token_path = handler._token_store_path()
        try:
            result = service.clear_owner(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                room=room,
                token_store_path=token_path,
            )
            if bool(result.get("success", True)):
                prev = result.get("previous_owner")
                if prev:
                    handler.screen.show_system_message(
                        f" Cleared owner '{prev}' for room '{room}'"
                    )
                else:
                    handler.screen.show_system_message(
                        f" Room '{room}' is now system-owned"
                    )
            else:
                msg = result.get("message", "operation not successful")
                handler.screen.show_system_message(f" {msg}")
        except Exception as e:
            handler.screen.show_system_message(f" /clear-owner failed: {e}")

    def _destroy_room(args: str) -> None:
        room = args.strip()
        if not room:
            handler.screen.show_system_message("Usage: /destroy-room <name>")
            return
        service = handler._room_service()
        token_path = handler._token_store_path()
        try:
            service.set_policy(
                host=handler.controller.host,
                port=handler.controller.port,
                user=handler.controller.username,
                room=room,
                policy="teardown",
                token_store_path=token_path,
            )
            handler.screen.show_system_message(f" Room '{room}' set to teardown")
        except Exception as e:
            handler.screen.show_system_message(f" /destroy-room failed: {e}")

    def _history(args: str) -> None:
        parts = args.split()
        limit = 50
        since = 0
        try:
            if len(parts) >= 1 and parts[0]:
                limit = int(parts[0])
            if len(parts) >= 2 and parts[1]:
                since = int(parts[1])
        except Exception:
            handler.screen.show_system_message("Usage: /history [limit] [since_id]")
            return

        handler.screen.show_system_message(
            f" Fetching history (limit={limit}, since_id={since})..."
        )

        def _worker() -> None:
            try:
                token_path = handler._token_store_path()
                with create_mp2_client(
                    handler.controller.host,
                    handler.controller.port,
                    timeout=10.0,
                    token_store_path=token_path,
                ) as client:
                    events = client.get_history(
                        handler.controller.username,
                        handler.screen.current_room,
                        since_id=since,
                        limit=limit,
                        include_text=True,
                        include_files=True,
                    )

                def _apply_history() -> None:
                    ev_list = list(events or [])
                    if not ev_list:
                        handler.screen.show_system_message("(no history)")
                        return

                    handler.screen.show_system_message(
                        f"── History (limit={limit}, since_id={since}) ──"
                    )

                    for ev in ev_list:
                        try:
                            setattr(ev, "_from_history", True)
                        except Exception:
                            pass
                        try:
                            handler.screen._process_event(ev)  # type: ignore[attr-defined]
                        except Exception:
                            # Best-effort textual fallback
                            try:
                                sender = getattr(ev, "sender", "") or getattr(
                                    ev, "display_token", ""
                                )
                                payload = getattr(ev, "payload", b"")
                                text = ""
                                if isinstance(payload, (bytes, bytearray)):
                                    try:
                                        text = payload.decode("utf-8")
                                    except Exception:
                                        text = "[Encrypted or binary payload]"
                                else:
                                    text = str(payload)
                                handler.screen.show_system_message(
                                    f"[{getattr(ev, 'event_id', '?')}] {sender}: {text}"
                                )
                            except Exception:
                                handler.screen.show_system_message(
                                    f"[{getattr(ev, 'event_id', '?')}] <unparsed>"
                                )

                    handler.screen.show_system_message("── End of history ──")

                handler.screen.app.call_from_thread(_apply_history)
            except Exception as e:
                handler.screen.app.call_from_thread(
                    lambda e=e: handler.screen.show_system_message(
                        f" /history failed: {e}"
                    )
                )

        handler.screen.app.run_worker(_worker, thread=True)

    def _local_history(args: str) -> None:
        """Display history from local storage (14F offline access)."""
        parts = args.split()
        limit = 50
        since = 0
        try:
            if len(parts) >= 1 and parts[0]:
                limit = int(parts[0])
            if len(parts) >= 2 and parts[1]:
                since = int(parts[1])
        except Exception:
            handler.screen.show_system_message(
                "Usage: /local-history [limit] [since_seq]"
            )
            return

        room = handler.screen.current_room
        if not room:
            handler.screen.show_system_message("Not connected to a room")
            return

        # Get raw LocalEvent objects from local store for robust offline rendering
        events = handler.controller.get_local_events(room, since_seq=since, limit=limit)
        sync_state = handler.controller.get_local_sync_state(room)

        if not events:
            handler.screen.show_system_message(
                f"(no local history for '{room}', sync_state={sync_state})"
            )
            return

        handler.screen.show_system_message(
            f"── Local History (limit={limit}, since_seq={since}, sync={sync_state}) ──"
        )

        # Import VerificationStatus for display symbols
        from ming_drlms.core.event_store import VerificationStatus

        for ev in events:
            # Determine verification status indicator
            if ev.verified == VerificationStatus.VERIFIED:
                status = "✓"
            elif ev.verified == VerificationStatus.FAILED:
                status = "✗"
            elif ev.verified == VerificationStatus.NO_SIGNATURE:
                status = "?"
            else:
                status = "·"

            # Decode content as UTF-8 when possible
            text = ""
            if ev.content:
                if isinstance(ev.content, (bytes, bytearray)):
                    try:
                        text = ev.content.decode("utf-8")
                    except Exception:
                        text = f"[binary {len(ev.content)} bytes]"
                else:
                    text = str(ev.content)

            # Render one line per event, independent of ChatScreen._process_event
            # Use server_seq as the primary sequence, and prefix with verification mark
            prefix = f"[{status}][seq={ev.server_seq}]"
            # Show a short hash prefix for the event_id to help cross-checking
            hash_prefix = ev.event_id[:8] if ev.event_id else "?"
            line = f"{prefix}[{hash_prefix}] {ev.sender_id}: {text}"
            handler.screen.show_system_message(line)

        handler.screen.show_system_message("── End of local history ──")

    handler.commands.update(
        {
            "/rooms": _rooms,
            "/join": _join,
            "/create-room": _create_room,
            "/room-info": _room_info,
            "/members": _members,
            "/leave": _leave,
            "/set-policy": _set_policy,
            "/set-storage": _set_storage,
            "/transfer-owner": _transfer_owner,
            "/clear-owner": _clear_owner,
            "/destroy-room": _destroy_room,
            "/history": _history,
            "/local-history": _local_history,
        }
    )
