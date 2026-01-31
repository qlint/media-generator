import json
import re
from typing import Any, Optional

def extract_json_object(text: str) -> Optional[Any]:
    if not text:
        return None
    # Try to find the first JSON object or array in the text
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        return None
    blob = m.group(1)
    try:
        return json.loads(blob)
    except Exception:
        return None
