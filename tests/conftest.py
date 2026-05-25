"""Config compartida de pytest para cv-worker."""
import os
import sys
from pathlib import Path

# Setear env vars de testing ANTES de importar src.*
os.environ["SENTRY_DSN"]        = ""
os.environ["METRICS_ENABLED"]   = "0"
os.environ["WEBHOOK_SECRET"]    = "test-secret-1234567890"
os.environ["BG_API_URL"]        = "http://test"
os.environ["BG_API_KEY"]        = "test-key"
os.environ["SHEET_ID"]          = "test-sheet-id"
os.environ["SA_JSON"]           = '{"type":"service_account","client_email":"test@test.iam.gserviceaccount.com","private_key":"-----BEGIN PRIVATE KEY-----\\ntest\\n-----END PRIVATE KEY-----\\n","token_uri":"https://oauth2.googleapis.com/token"}'

sys.path.insert(0, str(Path(__file__).parent.parent))
