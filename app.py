import os, sys
BASE_DIR = os.path.dirname(__file__)
APP_DIR = os.path.join(BASE_DIR, "LOE_Excel_Macro_Automation_System", "loe_excel_macro_system", "app")
sys.path.insert(0, APP_DIR)
from web_app import app
