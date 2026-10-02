"""Print the results table from a NanoDrop .twbk workbook.

Usage:
    read_nanodrop.exe "\\\\fs02\\SharedFiles\\NANODROP\\Josh\\2026_09_30_Nucleic Acid.twbk"
"""
import os
import sys

from tbwk import Worksheet


def prop(m, key):
    """Return a value from the NanoDrop's results table, or NaN if missing."""
    bag = m.get_property_bag()
    return bag.get_property(key).get_value().get_value() if bag.has_property(key) else float("nan")


def main():
    # Avoid crashes on Windows consoles that can't encode 'µ'
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass

    if len(sys.argv) != 2:
        print('Usage: read_nanodrop "<path to .twbk file>"')
        sys.exit(1)

    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"File not found: {path}")
        sys.exit(1)

    worksheet = Worksheet.import_worksheet(path)

    print(f"{'Sample':20}{'Time':21}{'ng/µl':>10}{'260/280':>9}{'260/230':>9}")
    for m in worksheet:
        print(f"{m.title:20}{m.get_time():%Y-%m-%d %H:%M:%S}  "
              f"{prop(m, 'Nucleic Acid'):>9.1f}{prop(m, '260/280'):>9.2f}{prop(m, '260/230'):>9.2f}")


if __name__ == "__main__":
    main()
