"""Copy the tbwk package from the current Python environment into ./vendor.

Run with jlenv's python by build_small.bat when twbk-opener can't be installed from pip.
"""
import os
import shutil

import tbwk

src = tbwk.__file__
os.makedirs("vendor", exist_ok=True)
if os.path.basename(src) == "__init__.py":          # tbwk is a package folder
    pkg_dir = os.path.dirname(src)
    print("Found tbwk package at", pkg_dir)
    shutil.copytree(pkg_dir, os.path.join("vendor", "tbwk"),
                    ignore=shutil.ignore_patterns("__pycache__"))
else:                                               # tbwk is a single module file
    print("Found tbwk module at", src)
    shutil.copy2(src, "vendor")
