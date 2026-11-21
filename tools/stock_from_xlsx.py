"""Читает выгрузку .xlsx таблицы «Нунчи склад — остатки»."""
import json, os, sys, openpyxl
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "robot", "fn"))
from parsers import parse_stock

def parse(path):
    ws = openpyxl.load_workbook(path, data_only=True).active
    return parse_stock(list(ws.iter_rows(values_only=True)))
