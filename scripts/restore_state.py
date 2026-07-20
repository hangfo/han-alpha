#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from hanalpha.ops.backup import restore_databases


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify and restore Han Alpha SQLite backups")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    arguments = parser.parse_args()
    print(
        restore_databases(
            arguments.manifest, arguments.destination, overwrite=arguments.overwrite
        )
    )


if __name__ == "__main__":
    main()
