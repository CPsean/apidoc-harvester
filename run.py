#!/usr/bin/env python3
"""CLI entry. Usage: python run.py config/fadada.yaml"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harvester import config_loader, pipeline  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("usage: python run.py <config.yaml>")
        sys.exit(2)
    config_path = sys.argv[1]
    cfg = config_loader.load_config(config_path)
    # Top of the acquisition ladder: if the config points at an already-published
    # spec, ingest it directly instead of scraping pages.
    if "spec_source" in cfg:
        from harvester import spec_import
        report = spec_import.run(config_path)
    else:
        report = pipeline.run(config_path)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if report["fails"]:
        print("\nFAILS:")
        for f in report["fails"]:
            print("  -", f)
    if report["warns"]:
        print("\nWARNS:")
        for w in report["warns"]:
            print("  -", w)
    print("\nOK" if report["ok"] else "\nNOT OK")
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
