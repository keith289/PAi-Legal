"""
PAi-Legal: Standalone Private Legal Workspace
"""

__version__ = "1.0.0"
__author__ = "PAi-Legal Team"

from .database import LegalDatabaseManager
from .ai import LocalAIEngine
from .ocr import DocumentOCREngine
from .drafting import DocumentDrafterEngine

__all__ = [
    "LegalDatabaseManager",
    "LocalAIEngine",
    "DocumentOCREngine",
    "DocumentDrafterEngine",
]
