"""Pone la raíz del proyecto en sys.path para que `from src import ...` ande.

`python -m pytest` agrega el cwd al path y disimula el problema; `pytest` a secas
(lo que corre CI) no. Con este conftest en la raíz, pytest la agrega solo, y los
tests corren igual desde donde los llames.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = str(Path(__file__).resolve().parent)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
