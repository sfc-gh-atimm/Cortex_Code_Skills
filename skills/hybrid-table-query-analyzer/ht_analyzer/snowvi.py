import json
from typing import Any, Dict

from snowvi_features import extract_snowvi_features


def load_snowvi_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


__all__ = ["load_snowvi_json", "extract_snowvi_features"]
