"""Читает выгрузку .xlsx таблицы ТТК линейки и пишет JSON с рецептами для сайта."""
import json, os, sys, openpyxl
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "robot", "fn"))
from parsers import parse_ttk

def parse(path):
    ws = openpyxl.load_workbook(path, data_only=True).active
    return parse_ttk(list(ws.iter_rows(values_only=True)))

if __name__ == "__main__":
    data = parse(sys.argv[1])
    json.dump(data, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(len(data["tonics"]), "рецептов,", len(data["ref"]), "позиций справочника")
