"""
Generate a flowchart for user management (add/passwd/del/list) using graphviz.
"""

from graphviz import Digraph


def build() -> Digraph:
    g = Digraph("user_mgmt")
    g.attr(rankdir="LR", labelloc="t", label="User Management Flow")

    g.node("start", "CLI entry: ming-drlms user ...", shape="ellipse")
    g.node("resolve", "resolve data_dir (env/yaml/override)")
    g.node("parse", "parse users.txt (argon2/legacy/unknown)")
    g.node("add", "add: prompt pw x2 -> argon2id")
    g.node("passwd", "passwd: ensure exists -> argon2id")
    g.node("del", "del: rm record (force?)")
    g.node("list", "list: rich table / --json")
    g.node("write", "atomic write: tmp + fsync + replace + chmod 600")
    g.node("end", "exit code")

    g.edges([("start", "resolve"), ("resolve", "parse")])
    g.edge("parse", "add")
    g.edge("parse", "passwd")
    g.edge("parse", "del")
    g.edge("parse", "list")
    g.edge("add", "write")
    g.edge("passwd", "write")
    g.edge("del", "write")
    g.edge("list", "end")
    g.edge("write", "end")
    return g


if __name__ == "__main__":
    dot = build()
    dot.render("user_mgmt_flow", format="png", cleanup=True)
