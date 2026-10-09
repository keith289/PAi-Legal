# PAi-Legal: Standalone Private Legal Workspace

[![License: Commercial / Enterprise](https://img.shields.io/badge/License-Commercial-blue.svg)](#pricing--plans)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Privacy Guaranteed](https://img.shields.io/badge/Data%20Privacy-100%25%20Local%20%26%20Offline-success.svg)](#security--privacy)
[![Build Status](https://img.shields.io/badge/Build-Passing-brightgreen.svg)](#installation--setup)

**PAi-Legal** is a Next-Generation, Privacy-First Standalone Legal Workspace designed for individual practitioners, small law firms, and enterprise legal departments.

Unlike cloud-based AI tools that compromise client confidentiality by uploading sensitive contracts to third-party servers, **PAi-Legal runs 100% locally on your hardware**. No data ever leaves your control.

---

## 💰 Pricing & Plans

Simple, predictable pricing for legal work. **Pay for seats and active matters — nothing else is metered.**
No per-page, per-query, or per-AI-call fees inside an active matter. All plans work online or fully offline with signed license files.

| Plan | Seats | Included Active Matters | Price (Monthly) | Price (Annual - Save ~33%) | Extra Active Matter | Extra Seat |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Solo** *(Individual Practitioners)* | 1 | 5 | **$149** / mo | **$1,190** / yr | $29 / mo | N/A |
| **Practice** *(Small Firms & Growing Practices)* | Up to 5 | 20 *(Shared Pool)* | **$449** / mo | **$3,590** / yr | $24 / mo | $79 / mo |
| **Firm** *(Established Firms)* | Up to 15 | 75 *(Shared Pool)* | **$1,299** / mo | **$10,390** / yr | $19 / mo | $69 / mo |
| **Enterprise** *(Custom Deployment)* | Custom | Custom Volume | **Contact Us** | **Contact Us** | Custom | Custom |

### 🎁 14-Day Free Trial
- Start with **1 seat and 2 active matters for 14 days**.
- **Credit card required to begin free trial.**
- Everything you create stays yours if you continue or leave.

---

## ⚙️ How Billing Works

- **Seat**: A named user who can open and work in the product.
- **Active Matter**: A live case or matter. It counts when you create it or run the first analysis. Archive a matter when completed, and it stops counting against your quota while remaining **fully readable** forever.
- **Offline Signed Licenses**: Offline deployments use a signed cryptographic capacity file (`seats + matter allowance + expiry`). Refresh when you choose to go online.

---

## 🌟 Key Features

- 🔒 **Zero Data Leakage (100% Offline)**
  All AI analysis, OCR, document indexation, and drafting are computed locally on your device hardware. Compliant with attorney-client privilege, HIPAA, GDPR, and SOC 2.
- 🧠 **Embedded Local AI Engine (Llama.cpp / GGUF)**
  High-performance offline Large Language Model support tailored for contract review, clause extraction, legal risk assessment, and summary generation.
- 📄 **Multiformat OCR & Ingestion Engine**
  Extract text seamlessly from scanned PDFs, images, RTF, Word docs, PowerPoint presentations, Excel sheets, and Outlook `.msg` emails using integrated Tesseract and PyMuPDF engines.
- ⚖️ **Interactive Legal Document Drafter**
  Draft court motions, pleadings, briefs, and client agreements with auto-formatting for jurisdiction rules.
- 🗄️ **Encrypted Matter & Case Database**
  Organize client files, evidence, court filings, and research notes in a secure, locally encrypted SQLite database store.

---

## 🚀 Quick Start & Installation

### Option 1: Install via Pip (Developer / Source)

```bash
# Clone the repository
git clone https://github.com/your-org/PAi-Legal.git
cd PAi-Legal

# Install dependencies and PAi-Legal package in editable mode
pip install -e .

# Launch PAi-Legal Workspace
pai-legal --mode cli
```

### Option 2: Run Launcher Directly

```bash
python run_pai_legal.py
```

### Option 3: Standalone Executable (.exe / Binary Build)

Generate a standalone executable using PyInstaller:

```bash
pip install pyinstaller
pyinstaller PAiLegal.spec
```
The compiled executable will be available under `dist/PAiLegal/`.

---

## 🛡️ Security & FAQ

- **Can I switch between online and offline?**
  Yes. Same account, same matters. Offline uses a signed license you refresh when convenient.
- **What happens if I go over my active matters?**
  You can add individual matters ($19–$29/mo) or move to the next plan. Existing work is never locked or deleted.
- **Do you train on my data?**
  No. Zero data collection or remote AI telemetry.
- **Is there a long-term contract?**
  Monthly plans are month-to-month. Annual plans are prepaid for the year.

---

*PAi-Legal — The Private AI Legal Assistant That Keeps Your Confidential Data Offline.*
