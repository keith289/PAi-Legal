"""
PAi-Legal Application Launcher & Interface Runner
"""

import sys
import os
import argparse
from pai_legal.database import LegalDatabaseManager
from pai_legal.ai import LocalAIEngine
from pai_legal.ocr import DocumentOCREngine
from pai_legal.drafting import DocumentDrafterEngine


def run_cli():
    print("==================================================")
    print(" PAi-Legal: Standalone Private Legal Workspace v1.0")
    print("==================================================")

    db = LegalDatabaseManager()
    matters = db.list_matters()
    print(f"[*] Local Legal Database Initialized. Active matters: {len(matters)}")

    ai = LocalAIEngine()
    res = ai.generate_legal_analysis("Review initial matter status.")
    print("\n[+] Local AI Status:")
    print(res)

    print("\n[*] PAi-Legal workspace ready for confidential legal operations.")


def main():
    parser = argparse.ArgumentParser(description="PAi-Legal Standalone Workspace")
    parser.add_argument("--mode", choices=["cli", "gui", "web"], default="cli", help="Workspace interface mode")
    args = parser.parse_args()

    if args.mode == "cli":
        run_cli()
    else:
        print(f"Starting PAi-Legal in {args.mode} mode...")
        run_cli()


if __name__ == "__main__":
    main()
