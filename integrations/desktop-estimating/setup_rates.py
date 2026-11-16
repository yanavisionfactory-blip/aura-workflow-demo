"""Create a blank rate book; never insert fictional prices into a user's Rates folder."""
import argparse
from pathlib import Path

import xlsxwriter
from estimate_core import RATE_COLUMNS


def create_template(folder):
    directory = Path(folder) / "Rates"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "Approved-Rates.xlsx"
    if path.exists():
        return
    with xlsxwriter.Workbook(path) as workbook:
        sheet = workbook.add_worksheet("Rates")
        header = workbook.add_format({"bold": True, "bg_color": "#20334A", "font_color": "white"})
        sheet.write_row(0, 0, RATE_COLUMNS, header)
        sheet.freeze_panes(1, 0)
        sheet.set_column(0, 8, 20)
        sheet.set_column(6, 6, 50)
        notes = workbook.add_worksheet("Instructions")
        notes.set_column(0, 0, 110)
        for row, line in enumerate([
            "Enter approved prices on Rates. The template contains no sample prices.",
            "cost_code must match PlanSwift Item # exactly; store codes as text. unit must match the Qty unit.",
            "material_rate, labor_rate and equipment_rate are separate amounts per unit. Enter explicit 0 where not applicable.",
            "currency: USD, CAD, EUR, GBP, AUD or NZD. source: supplier quote or approved rate reference.",
            "valid_from and valid_to: YYYY-MM-DD. Only one effective rate per code/unit/currency is allowed.",
            "Use literal approved values, not formulas. Remove unused rows; do not add extra columns.",
            "Do not use an all-in composite rate plus separate labor/equipment: that would double count costs.",
        ]):
            notes.write_string(row, 0, line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True)
    create_template(parser.parse_args().folder)
