#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from hanalpha.ops.backup import backup_databases


def main() -> None:
    parser = argparse.ArgumentParser(description="Create consistent Han Alpha SQLite backups")
    parser.add_argument("--source", action="append", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    arguments = parser.parse_args()
    print(backup_databases(tuple(arguments.source), arguments.destination))


if __name__ == "__main__":
    main()
