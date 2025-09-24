#!/usr/bin/env python3
"""
Generate the system architecture diagram for ming-drlms.

Usage:
  python docs/diagrams/architecture/system_architecture.py --out docs/diagrams/out/system_architecture.png
"""

import argparse
from graphviz import Digraph


def build_graph() -> Digraph:
    g = Digraph("ming_drlms_arch", format="png")
    g.attr(rankdir="LR", concentrate="true", fontsize="11")

    # Nodes
    g.node(
        "cli",
        "Python CLI\n(Typer)",
        shape="box",
        style="rounded,filled",
        fillcolor="#f0f8ff",
    )
    g.node(
        "server",
        "C Server\n(log_collector_server)",
        shape="box",
        style="rounded,filled",
        fillcolor="#fff5ee",
    )
    g.node(
        "ipc",
        "libipc\n(SharedLogBuffer)",
        shape="box",
        style="rounded,filled",
        fillcolor="#f5fffa",
    )
    g.node(
        "agent",
        "Agent & Tools\n(log_agent / ipc_sender / log_consumer / proc_launcher)",
        shape="box",
        style="rounded,filled",
        fillcolor="#fafad2",
    )
    g.node(
        "storage",
        "Storage\n(server_files/rooms/*)\n(events.log / texts/ / files/ / ops_audit.log)",
        shape="folder",
    )

    # Edges
    g.edge(
        "cli",
        "server",
        label="TCP text protocol\nLOGIN/LIST/UPLOAD/DOWNLOAD\nSUB/HISTORY/PUBT/PUBF",
    )
    g.edge("server", "ipc", label="shm_write/read\n(semaphores + rwlock)")
    g.edge("agent", "ipc", label="produce/consume\n(ipc_sender/log_consumer)")
    g.edge("server", "storage", label="events/logs/files")

    return g


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="output png path (without .png)")
    args = ap.parse_args()
    g = build_graph()
    # graphviz 'render' appends the format extension automatically
    g.render(filename=args.out, cleanup=True)


if __name__ == "__main__":
    main()
