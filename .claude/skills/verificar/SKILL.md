---
name: verificar
description: Verifica un cambio antes de darlo por terminado - ruff, pytest (con prueba de humo de las páginas), revisión del diff y chequeo visual si hace falta. Usar al terminar cualquier cambio de código en App-Coti.
---

1. `.venv/Scripts/ruff.exe check .` y `.venv/Scripts/python.exe -m pytest -q`. `tests/test_app_smoke.py` abre cada página con datos sintéticos: si una página tira una excepción, aparece acá. Corregir antes de seguir.
2. Si se agregó o cambió una función pura en `utils/`, confirmar que tiene test (agregarlo si falta).
3. Revisar `git diff` y confirmar que:
   - no hay credenciales, teléfonos ni datos de contactos;
   - no se tocaron archivos ajenos al pedido.
4. Sólo si el cambio es visual (layout, colores, textos de gráficos), pedirle al usuario que lo mire con `streamlit run app.py`, indicando página y tarjeta. Los errores de ejecución ya los cubre la prueba de humo.
5. Si cambió el comportamiento de una sección, correr `/sync-requisitos`.
6. Resumir en 2-4 líneas qué cambió y qué quedó pendiente de probar.
