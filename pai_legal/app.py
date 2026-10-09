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
from pai_legal.licensing import LicenseManager


def run_cli():
    print("==================================================")
    print(" PAi-Legal: Standalone Private Legal Workspace v1.0")
    print("==================================================")

    db = LegalDatabaseManager()
    lm = LicenseManager()

    plan_info = lm.get_plan_info()
    active_matters = db.count_active_matters()

    print(f"[*] License Plan: {plan_info['tier_name']} ({plan_info['mode'].upper()} Mode)")
    print(f"[*] Seats Included: {plan_info['seats']}")
    print(f"[*] Active Matter Quota: {active_matters} / {plan_info['allowed_active_matters']} active matters in use")

    if plan_info["is_trial"]:
        print("    (14-Day Free Trial - Credit card required to begin. Upgrade anytime to keep adding matters)")

    ai = LocalAIEngine()
    res = ai.generate_legal_analysis("Review initial matter status.")
    print("\n[+] Local AI Status:")
    print(res)

    print("\n[*] PAi-Legal workspace ready for confidential legal operations.")


def create_matter_cmd(title: str, case_number: str = "", client_name: str = ""):
    db = LegalDatabaseManager()
    lm = LicenseManager()

    active_count = db.count_active_matters()
    can_create, msg = lm.check_can_create_matter(active_count)

    if not can_create:
        print(f"[ERROR] Cannot create active matter: {msg}")
        return None

    matter_id = db.create_matter(title, case_number, client_name)
    print(f"[SUCCESS] Created matter '{title}' (ID: {matter_id}). Active matters: {active_count + 1}/{lm.get_plan_info()['allowed_active_matters']}")
    return matter_id


def main():
    parser = argparse.ArgumentParser(description="PAi-Legal Standalone Workspace")
    parser.add_argument("--mode", choices=["cli", "gui", "web"], default="cli", help="Workspace interface mode")
    parser.add_argument("--create-matter", help="Title of new matter to create")
    args = parser.parse_args()

    if args.create_matter:
        create_matter_cmd(args.create_matter)
    elif args.mode == "cli":
        run_cli()
    else:
        print(f"Starting PAi-Legal in {args.mode} mode...")
        run_cli()


if __name__ == "__main__":
    main()
