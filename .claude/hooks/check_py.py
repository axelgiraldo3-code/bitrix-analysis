"""Hook PostToolUse: después de editar un .py, verifica que compile.

Si hay error de sintaxis sale con código 2 y el mensaje vuelve a Claude
para que lo corrija en el momento."""
import json
import py_compile
import sys

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
sys.exit(0)
