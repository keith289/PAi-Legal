# PAi-Legal: Standalone Private Legal Workspace

[![License: Commercial Proprietary](https://img.shields.io/badge/License-Commercial%20Proprietary-blue.svg)](#commercial-proprietary-license)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Privacy Guaranteed](https://img.shields.io/badge/Data%20Privacy-100%25%20Local%20%26%20Offline-success.svg)](#security--privacy)
[![Build Status](https://img.shields.io/badge/Build-Passing-brightgreen.svg)](#installation--setup)

**PAi-Legal** is a Next-Generation, Privacy-First Standalone Legal Workspace designed for individual practitioners, small law firms, and enterprise legal departments.

All source code, compiled binaries, and associated assets are **Commercial Proprietary Software**. Redistribution, unauthorized copying, reverse engineering, or usage without a valid paid commercial license key is strictly prohibited.

---

## 🔒 Commercial Proprietary License & Protection

PAi-Legal is distributed under a **Closed-Source Commercial Proprietary License**.

- **No Open Source Redistribution**: The source code and compiled executables are proprietary property of PAi-Legal / Y Private AI.
- **Licensing Enforcement**: Usage requires a cryptographically signed license file or token issued upon verified subscription or trial checkout with credit card verification.
- **Compiled Binary Distribution**: Production releases are compiled into secure standalone executables using PyInstaller / Cython obfuscation, ensuring business logic and licensing checks cannot be bypassed.

---

## 💰 Pricing & Plans

Simple, predictable pricing for legal work. **Pay for seats and active matters — nothing else is metered.**
No per-page, per-query, or per-AI-call fees inside an active matter. All plans work online or fully offline with signed license files.

| Plan | Seats | Included Active Matters | Price (Monthly) | Price (Annual - Save ~33%) | Extra Active Matter | Extra Seat |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Solo** *(Individual Practitioners)* | 1 | 5 | **$149** / mo | **$1,190** / yr | $29 / mo | N/A |
| **Practice** *(Small Firms & Growing Practices)* | Up to 5 | 20 *(Shared Pool)* | **$449** / mo | **$3,590** / yr | $79 / mo | $24 / mo |
| **Firm** *(Established Firms)* | Up to 15 | 75 *(Shared Pool)* | **$1,299** / mo | **$10,390** / yr | $69 / mo | $19 / mo |
| **Enterprise** *(Custom Deployment)* | Custom | Custom Volume | **Contact Us** | **Contact Us** | Custom | Custom |

### 🎁 14-Day Free Trial
- Start with **1 seat and 2 active matters for 14 days**.
- **Credit card required to begin free trial.**
- Everything you create stays yours if you continue or leave.

---

## ⚙️ How Billing & Licensing Works

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

## 🚀 Building & Packaging Binaries

To produce closed-source compiled standalone binaries for commercial distribution:

```bash
# Build binary executable package
pip install pyinstaller
pyinstaller PAiLegal.spec
```
The compiled executable output will be located in `dist/PAiLegal/`.

---

## 🛡️ Copyright & Contact

Copyright © 2026 PAi-Legal / Y Private AI. All Rights Reserved.
For licensing, sales inquiries, or custom enterprise deployments:
📧 **Email**: sales@yprivateai.com / contact@pailegal.com
🌐 **Website**: [https://yprivateai.com](https://yprivateai.com)
