"""Список Google-таблиц в папке «claude рецепты нунчи» (через мост). Пишет robot/status/drive_list.json."""
import json, os, sys
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "robot", "fn"))
import main
try:
    files = main.bridge([{"action": "list"}])[0]["files"]
    out = {"ok": True, "files": sorted(files, key=lambda f: f["modified"], reverse=True)}
except Exception as e:
    out = {"ok": False, "error": str(e)}
json.dump(out, open(os.path.join(ROOT, "robot", "status", "drive_list.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(out.get("files", out)[:10] if out["ok"] else out)
