"""Hook PostToolUse: después de editar un .py, verifica que compile y le aplica ruff.

Si hay error de sintaxis o ruff deja errores sin corregir, sale con código 2 y
el mensaje vuelve a Claude para que lo corrija en el momento. Sin ruff en
.venv, sólo se verifica la sintaxis."""

import json
import py_compile
import subprocess
import sys
from pathlib import Path

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
path = (data.get("tool_input") or {}).get("file_path", "")
if not path.endswith(".py"):
    sys.exit(0)
try:
    py_compile.compile(path, doraise=True)
except py_compile.PyCompileError as e:
    print(f"Error de sintaxis en {path}:\n{e.msg}", file=sys.stderr)
    sys.exit(2)

ruff = Path(__file__).resolve().parents[2] / ".venv" / "Scripts" / "ruff.exe"
if not ruff.exists():
    sys.exit(0)
subprocess.run([str(ruff), "format", "-q", path], capture_output=True)
check = subprocess.run(
    [str(ruff), "check", "--fix", "-q", path], capture_output=True, text=True, encoding="utf-8"
)
if check.returncode != 0:
    print(f"ruff en {path}:\n{check.stdout or check.stderr}", file=sys.stderr)
    sys.exit(2)
sys.exit(0)
