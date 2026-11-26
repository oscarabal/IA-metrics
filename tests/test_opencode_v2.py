"""The OpenCode suite against a database as OpenCode 2.x writes it (session_v2, session_message,
session_part and the models catalog in the kv table, no models.json). See collectors/opencode/oc_schema.py."""
import os
import runpy

os.environ["OC_FIXTURE_SCHEMA"] = "v2"
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_opencode.py"), run_name="__main__")
