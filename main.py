import sys

import uilib  # noqa: F401 -- select the Qt backend before app.py imports pyplot

from app import App

app = App(sys.argv)
sys.exit(app.exec())
