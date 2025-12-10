from __future__ import annotations

from typing import Any


def register_system_commands(handler: Any) -> None:
    if hasattr(handler, "_handle_clear"):
        handler.commands["/clear"] = handler._handle_clear
    if hasattr(handler, "_handle_help"):
        handler.commands["/help"] = handler._handle_help

    def _ephemeral(args: str) -> None:
        arg = (args or "").strip().lower()
        if arg in {"on", "enable", "true", "1"}:
            handler.controller.set_ephemeral_mode(True)
            handler.screen.show_system_message("Ephemeral mode: ON")
        elif arg in {"off", "disable", "false", "0"}:
            handler.controller.set_ephemeral_mode(False)
            handler.screen.show_system_message("Ephemeral mode: OFF")
        elif arg in {"toggle", ""}:
            try:
                current = getattr(handler.controller, "_ephemeral", False)
            except Exception:
                current = False
            handler.controller.set_ephemeral_mode(not current)
            handler.screen.show_system_message(
                "Ephemeral mode: ON" if not current else "Ephemeral mode: OFF"
            )
        else:
            handler.screen.show_system_message("Usage: /ephemeral [on|off|toggle]")

        # Refresh header indicator if supported
        try:
            if hasattr(handler.screen, "_update_ephemeral_mode_indicator"):
                handler.screen._update_ephemeral_mode_indicator()
        except Exception:
            pass

    def _send(args: str) -> None:
        text = (args or "").strip()
        if not text:
            handler.screen.show_system_message("Usage: /send <text>")
            return
        handler.controller.send_message(text)

    def _send_ephemeral(args: str) -> None:
        text = (args or "").strip()
        if not text:
            handler.screen.show_system_message("Usage: /send-ephemeral <text>")
            return
        handler.controller.send_message(text, ephemeral=True)

    handler.commands["/ephemeral"] = _ephemeral
    handler.commands["/send"] = _send
    handler.commands["/send-ephemeral"] = _send_ephemeral

    # Phase 16C: Multi-relay sync command
    def _sync(args: str) -> None:
        """Trigger multi-relay sync for current room."""
        result = handler.controller.sync_from_relays()
        if result.get("success"):
            handler.screen.show_system_message(
                f"[Sync] Synced {result.get('new_events', 0)} new events "
                f"from {result.get('relays_synced', 0)} relays"
            )
        else:
            # Prefer a detailed errors list if available
            err = result.get("error")
            if not err:
                errs = result.get("errors")
                if isinstance(errs, list) and errs:
                    err = "; ".join(str(e) for e in errs)
            if not err:
                err = "Unknown error"
            handler.screen.show_system_message(f"[Sync] Failed: {err}")

    # Phase 16A: Relay health status command
    def _health(args: str) -> None:
        """Show relay health status."""
        health_list = handler.controller.get_relay_health()
        if not health_list:
            handler.screen.show_system_message(
                "[Health] No relays configured or health checker not initialized"
            )
            return
        handler.screen.show_system_message("── Relay Health Status ──")
        for h in health_list:
            status = "✓" if h.get("healthy") else "✗"
            score = h.get("score", 0)
            latency = h.get("avg_latency_ms", 0)
            url = h.get("url", "?")
            handler.screen.show_system_message(
                f"  [{status}] {url}: score={score:.2f} latency={latency:.0f}ms"
            )
        handler.screen.show_system_message("─────────────────────────")

    handler.commands["/sync"] = _sync
    handler.commands["/health"] = _health

    # OFFQ-01: Offline queue management commands
    def _queue(args: str) -> None:
        """Show offline queue status or manage queue."""
        arg = (args or "").strip().lower()

        if arg in {"", "status"}:
            # Show queue statistics
            stats = handler.controller.get_queue_stats()
            if "error" in stats:
                handler.screen.show_system_message(f"[Queue] Error: {stats['error']}")
                return
            active = "✓" if stats.get("processing_active") else "✗"
            handler.screen.show_system_message("── Offline Queue Status ──")
            handler.screen.show_system_message(f"  Processor: {active}")
            handler.screen.show_system_message(
                f"  Pending:   {stats.get('pending', 0)}"
            )
            handler.screen.show_system_message(
                f"  Success:   {stats.get('success', 0)}"
            )
            handler.screen.show_system_message(f"  Failed:    {stats.get('failed', 0)}")
            handler.screen.show_system_message(f"  Total:     {stats.get('total', 0)}")
            handler.screen.show_system_message("───────────────────────────")

        elif arg == "clear":
            # Clear completed items
            result = handler.controller.clear_completed_queue()
            if "error" in result:
                handler.screen.show_system_message(f"[Queue] Error: {result['error']}")
            else:
                handler.screen.show_system_message(
                    f"[Queue] Cleared {result.get('cleared', 0)} completed items"
                )

        elif arg in {"retry", "flush"}:
            # Trigger immediate processing
            result = handler.controller.retry_queue_now()
            if "error" in result:
                handler.screen.show_system_message(f"[Queue] Error: {result['error']}")
            else:
                handler.screen.show_system_message(
                    f"[Queue] Processed {result.get('processed', 0)}: "
                    f"{result.get('succeeded', 0)} succeeded, "
                    f"{result.get('retrying', 0)} retrying, "
                    f"{result.get('failed', 0)} failed"
                )

        else:
            handler.screen.show_system_message("Usage: /queue [status|clear|retry]")

    handler.commands["/queue"] = _queue
