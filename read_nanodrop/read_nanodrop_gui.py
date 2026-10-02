"""NanoDrop .twbk reader with a simple window (no command line needed).

Double-click the exe: a file picker opens in the NanoDrop share. Pick a .twbk
(or paste a full path into the "File name" box) and the results table is shown.
A path can still be given as an argument, or a file dragged onto the exe.
"""
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

from tbwk import Worksheet

DEFAULT_DIR = r"\\fs02\SharedFiles\NANODROP\Josh"


def prop(m, key):
    """Return a value from the NanoDrop's results table, or NaN if missing."""
    bag = m.get_property_bag()
    return bag.get_property(key).get_value().get_value() if bag.has_property(key) else float("nan")


def results_text(path):
    worksheet = Worksheet.import_worksheet(path)
    lines = [f"{'Sample':20}{'Time':21}{'ng/µl':>10}{'260/280':>9}{'260/230':>9}"]
    for m in worksheet:
        lines.append(f"{m.title:20}{m.get_time():%Y-%m-%d %H:%M:%S}  "
                     f"{prop(m, 'Nucleic Acid'):>9.1f}{prop(m, '260/280'):>9.2f}{prop(m, '260/230'):>9.2f}")
    return "\n".join(lines)


class App:
    def __init__(self, root):
        self.root = root
        root.title("NanoDrop reader")
        root.geometry("760x420")

        bar = tk.Frame(root)
        bar.pack(fill="x", padx=8, pady=6)
        tk.Button(bar, text="Open .twbk…", command=self.choose).pack(side="left")
        tk.Button(bar, text="Copy results", command=self.copy).pack(side="left", padx=6)
        self.label = tk.Label(bar, text="", anchor="w")
        self.label.pack(side="left", fill="x", expand=True, padx=6)

        self.text = ScrolledText(root, font=("Consolas", 10), wrap="none")
        self.text.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def choose(self):
        start = DEFAULT_DIR if os.path.isdir(DEFAULT_DIR) else os.path.expanduser("~")
        path = filedialog.askopenfilename(
            title="Choose a NanoDrop workbook",
            initialdir=start,
            filetypes=[("NanoDrop workbook", "*.twbk"), ("All files", "*.*")],
        )
        if path:
            self.load(path)

    def load(self, path):
        if not os.path.isfile(path):
            messagebox.showerror("NanoDrop reader", f"File not found:\n{path}")
            return
        self.label.config(text="Reading…")
        self.root.update_idletasks()
        try:
            out = results_text(path)
        except Exception as e:
            self.label.config(text="")
            messagebox.showerror("NanoDrop reader", f"Could not read file:\n{path}\n\n{e}")
            return
        self.label.config(text=os.path.basename(path))
        self.text.delete("1.0", "end")
        self.text.insert("1.0", out)

    def copy(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.text.get("1.0", "end-1c"))


def main():
    root = tk.Tk()
    app = App(root)
    if len(sys.argv) > 1:
        root.after(100, lambda: app.load(sys.argv[1]))
    else:
        root.after(100, app.choose)
    root.mainloop()


if __name__ == "__main__":
    main()
