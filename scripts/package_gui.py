#!/usr/bin/env python3
"""Cross-platform helper to build the ming-drlms GUI with flet pack."""

from __future__ import annotations

import argparse
import contextlib
import os
import platform
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ENTRY = ROOT / "src" / "ming_drlms_gui" / "app.py"
ASSET_DIRS = [
    (ROOT / "src" / "ming_drlms_gui" / "assets", "assets"),
    (ROOT / "src" / "ming_drlms_gui" / "i18n", "i18n"),
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Package the ming-drlms GUI with flet pack"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "dist",
        help="Directory where flet pack should emit artifacts (maps to --distpath)",
    )
    parser.add_argument(
        "--name",
        default="DRLMS GUI",
        help="Display name of the GUI application",
    )
    parser.add_argument(
        "--product-name",
        default="ming-drlms",
        help="Product identifier used by the bundle",
    )
    parser.add_argument(
        "--description",
        default="A beautiful GUI client for ming-drlms",
        help="Short description embedded into the bundle",
    )
    parser.add_argument(
        "--copyright",
        default="DRLMS Team",
        help="Copyright notice embedded into the bundle",
    )
    parser.add_argument(
        "--icon",
        type=Path,
        default=None,
        help="Optional icon file passed through to flet pack",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="Deprecated no-op retained for backwards compatibility (flet pack already produces one-file bundles)",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the target output directory before packing",
    )
    return parser


def compute_add_data_arg(src: Path, dest: str) -> str:
    """Return a cross-platform --add-data argument."""

    separator = ";" if platform.system() == "Windows" else ":"
    return f"{src}{separator}{dest}"


@contextlib.contextmanager
def pushd(path: Path):
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def run_flet_pack(args: argparse.Namespace) -> None:
    if not APP_ENTRY.exists():
        raise FileNotFoundError(f"Flet app entry {APP_ENTRY} does not exist")

    output_dir = args.output.resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)

    work_dir_path = Path(
        tempfile.mkdtemp(prefix="flet_pack_", dir=str(output_dir.parent))
    )

    pack_cli_args = [
        str(APP_ENTRY),
        "--name",
        args.name,
        "--product-name",
        args.product_name,
        "--file-description",
        args.description,
        "--copyright",
        args.copyright,
        "--distpath",
        str(output_dir),
        "--yes",
    ]

    if args.icon:
        pack_cli_args.extend(["--icon", str(args.icon)])

    # args.onefile retained for compatibility but flet pack defaults to --onefile

    for src, dest in ASSET_DIRS:
        if not src.exists():
            raise FileNotFoundError(f"Required asset directory missing: {src}")
        pack_cli_args.extend(["--add-data", compute_add_data_arg(src, dest)])

    from flet.utils.pip import ensure_flet_cli_package_installed

    ensure_flet_cli_package_installed()

    from flet_cli.commands.pack import Command as FletPackCommand

    parser = argparse.ArgumentParser(prog="flet-pack")
    pack_command = FletPackCommand(parser)
    options = parser.parse_args(pack_cli_args)
    options.non_interactive = True

    existing_path = os.environ.get("PYTHONPATH")
    desired_path = (
        str(ROOT) if not existing_path else f"{ROOT}{os.pathsep}{existing_path}"
    )

    original_env = existing_path
    try:
        os.environ["PYTHONPATH"] = desired_path
        with pushd(work_dir_path):
            pack_command.handle(options)
        if platform.system() == "Windows":
            exe_candidates = list(output_dir.glob("*.exe"))
            if not exe_candidates:
                # Fallback: PyInstaller may emit a file without extension. Try to rename it.
                possible_names = {args.name, Path(args.name).stem}
                for candidate in possible_names:
                    source_path = output_dir / candidate
                    target_path = source_path.with_suffix(".exe")
                    if source_path.exists() and not target_path.exists():
                        source_path.rename(target_path)
                        exe_candidates.append(target_path)
                        break
            if not exe_candidates:
                raise FileNotFoundError(
                    "PyInstaller build succeeded but no .exe was produced in "
                    f"{output_dir}."
                )
    finally:
        if original_env is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = original_env
        shutil.rmtree(work_dir_path, ignore_errors=True)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    run_flet_pack(args)


if __name__ == "__main__":
    main()
