"""Improvement report page for Claude Code: the shared common.report_page with this collector's settings."""
from common import report_page as _shared
from pages import CSS

_shared.configure(product="Claude Code", session_pattern=r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", css=CSS)

render = _shared.render
error = _shared.error
to_html = _shared.to_html
