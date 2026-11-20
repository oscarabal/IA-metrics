"""Improvement report page for OpenCode: the shared common.report_page with this collector's settings."""
from common import report_page as _shared
from session_page import CSS

_shared.configure(product="OpenCode", session_pattern=r"ses_[A-Za-z0-9]+", css=CSS)

render = _shared.render
error = _shared.error
to_html = _shared.to_html
