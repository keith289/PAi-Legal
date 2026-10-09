# PAi-Legal: Standalone Private Legal Workspace

[![License: Commercial / Enterprise](https://img.shields.io/badge/License-Commercial-blue.svg)](#commercial-licensing)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Privacy Guaranteed](https://img.shields.io/badge/Data%20Privacy-100%25%20Local%20%26%20Offline-success.svg)](#key-features)
[![Build Status](https://img.shields.io/badge/Build-Passing-brightgreen.svg)](#installation--setup)

**PAi-Legal** is a Next-Generation, Privacy-First Standalone Legal Intelligence & Document Drafting Workspace designed for law firms, corporate legal departments, independent attorneys, and compliance teams.

Unlike cloud-based AI tools that compromise client confidentiality by uploading sensitive contracts to third-party servers, **PAi-Legal runs 100% locally on your workstation**. No data ever leaves your computer.

---

## 🌟 Key Features

- 🔒 **Zero Data Leakage (100% Offline)**
  All AI analysis, OCR, document indexation, and drafting are computed locally on your device hardware. Compliant with HIPAA, GDPR, SOC 2, and attorney-client privilege mandates.
- 🧠 **Embedded Local AI Engine (Llama.cpp / GGUF)**
  High-performance offline Large Language Model support tailored for contract review, clause extraction, legal risk assessment, and summary generation.
- 📄 **Multiformat OCR & Ingestion Engine**
  Extract text seamlessly from scanned PDFs, images, RTF, Word docs, PowerPoint presentations, Excel sheets, and Outlook `.msg` emails using integrated Tesseract and PyMuPDF engines.
- ⚖️ **Interactive Legal Document Drafter**
  Draft court motions, pleadings, briefs, and client agreements with auto-formatting for jurisdiction rules (Federal, State, and custom local court guidelines).
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

## 📐 Architecture & Repository Structure

```text
PAi-Legal/
├── pai_legal/                  # Core Application Package
│   ├── __init__.py             # Package exports
│   ├── app.py                  # Main CLI/GUI runner & entrypoint
│   ├── database.py             # SQLite matter & document database manager
│   ├── ai.py                   # Local LLM wrapper & legal intelligence
│   ├── ocr.py                  # PyMuPDF & Tesseract OCR pipeline
│   ├── drafting.py             # Motion & contract drafting engine
│   └── resources/              # Static resources & jurisdiction specs
│       ├── drafter.html        # Interactive Drafter UI asset
│       └── jurisdictions/      # Jurisdiction rule configuration JSONs
├── run_pai_legal.py            # Executable launcher script
├── PAiLegal.spec               # PyInstaller cross-platform spec
├── pyproject.toml              # Build & dependency metadata
└── requirements.txt            # Python dependencies
```

---

## 💼 Commercial Licensing & Sales

PAi-Legal is available under flexible commercial deployment models for solo practitioners, enterprise law firms, and corporate legal divisions:

| Feature Tier | Professional | Enterprise / Firm | Custom / On-Premise |
| :--- | :---: | :---: | :---: |
| **Local AI Legal Engine** | Full | Full | Custom Fine-tuned Models |
| **Document Ingestion & OCR** | Standard | High-Throughput | Unlimited |
| **Jurisdiction Rules** | US Federal / State | Unlimited | Custom Court Rules |
| **Support & Updates** | Standard Email | Dedicated 24/7 | SLA + On-Site Training |
| **Deployment** | Single Seat | Multi-User Firm | Enterprise Fleet |

For licensing, sales inquiries, or custom deployment options, please contact sales:
📧 **Email**: sales@yprivateai.com / contact@pailegal.com
🌐 **Website**: [https://yprivateai.com](https://yprivateai.com)

---

## 🛡️ Privacy & Security Compliance

PAi-Legal ensures absolute data sovereignty:
- **No Remote Telemetry**: Zero network requests or tracking calls.
- **Client Confidentiality Guaranteed**: Fully retains attorney work-product privilege.
- **Encrypted Local Storage**: Local database encrypted with AES-256 standard encryption primitives.

---

*PAi-Legal — The Private AI Legal Assistant That Keeps Your Confidential Data Offline.*
