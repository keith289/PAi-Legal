# Third-party notices

The PAi Legal Windows build bundles third-party document-processing components.
Their license files must remain with the distributed application.

## Tesseract OCR

Tesseract OCR is licensed under the Apache License 2.0. The packaging script
copies the complete selected Tesseract runtime directory, including its license
and notices, into `resources/tesseract`.

## Leptonica and runtime libraries

Tesseract distributions commonly include Leptonica and supporting image/runtime
libraries under their respective permissive licenses. Their accompanying
license files are preserved when the complete runtime directory is copied.

## llama.cpp

PAi Legal bundles the `llama-server` runtime from llama.cpp under the MIT
License. The complete selected runtime directory and its license file must be
preserved in the Store package.

## Downloaded AI models

Models are not included in the MSIX. During private-AI setup, the user chooses
a compatible model from the vetted catalog and the model is downloaded from
its Hugging Face publisher. The model's displayed license continues to apply.

## Python extraction libraries

PyMuPDF, Pillow, openpyxl, python-pptx, striprtf, extract-msg, and their bundled
dependencies retain their own license terms. The final release checklist must
collect the license metadata installed in the build environment and include it
in the Store package.

## cryptography

Encrypted backups use the PyCA `cryptography` package. PyCA cryptography is
dual licensed under the Apache License, Version 2.0, or the BSD license. Its
installed license metadata and bundled native components must remain in the
release package.
