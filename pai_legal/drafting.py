"""
PAi-Legal Document Drafter
Generates legal pleadings, agreements, motions, and correspondence based on jurisdiction templates and user inputs.
"""

import json
from typing import Dict, Any, Optional
from pathlib import Path


class DocumentDrafterEngine:
    """Legal document drafting engine."""

    def __init__(self, templates_dir: Optional[str] = None):
        self.templates_dir = templates_dir or Path(__file__).parent / "resources" / "jurisdictions"

    def draft_motion(self, caption_info: Dict[str, str], body_text: str, jurisdiction: str = "US-FED") -> str:
        """Draft a legal motion using structured variables."""
        court = caption_info.get("court", "IN THE UNITED STATES DISTRICT COURT")
        plaintiff = caption_info.get("plaintiff", "PLAINTIFF")
        defendant = caption_info.get("defendant", "DEFENDANT")
        case_no = caption_info.get("case_number", "Civil Action No. 00-CV-00000")
        title = caption_info.get("title", "MOTION FOR SUMMARY JUDGMENT")

        doc_html = f"""
        <div style="font-family: 'Times New Roman', serif; margin: 40px; line-height: 2.0; font-size: 12pt;">
            <div style="text-align: center; font-weight: bold; text-transform: uppercase;">
                {court}
            </div>
            <br/><br/>
            <table style="width: 100%; border-collapse: collapse;">
                <tr>
                    <td style="width: 50%; vertical-align: top;">
                        {plaintiff},<br/>
                        &nbsp;&nbsp;&nbsp;&nbsp;Plaintiff,<br/><br/>
                        v.<br/><br/>
                        {defendant},<br/>
                        &nbsp;&nbsp;&nbsp;&nbsp;Defendant.
                    </td>
                    <td style="width: 50%; vertical-align: top; border-left: 2px solid black; padding-left: 15px;">
                        Case No.: {case_no}<br/><br/>
                        <b>{title}</b>
                    </td>
                </tr>
            </table>
            <br/><br/>
            <div style="text-align: center; font-weight: bold; text-transform: uppercase;">
                {title}
            </div>
            <br/>
            <p style="text-indent: 0.5in;">
                COMES NOW the undersigned counsel, and hereby submits this {title} before this Honorable Court, and in support thereof states as follows:
            </p>
            <p style="text-indent: 0.5in;">
                {body_text}
            </p>
            <br/><br/>
            <div style="margin-left: 50%;">
                Respectfully submitted,<br/><br/>
                ____________________________________<br/>
                Counsel for Party<br/>
                PAi-Legal Workstation Generated
            </div>
        </div>
        """
        return doc_html
