---
name: verificar
description: Verifica un cambio antes de darlo por terminado - pytest, revisión del diff y chequeo de la app. Usar al terminar cualquier cambio de código en App-Coti.
---

1. Correr `python -m pytest -q`. Si algo falla, corregirlo antes de seguir.
2. Si se agregó o cambió una función pura en `utils/`, confirmar que tiene test en `tests/test_pure.py` (agregarlo si falta).
3. Revisar `git diff` y confirmar que:
   - no hay credenciales, teléfonos ni datos de contactos;
   - no se tocaron archivos ajenos al pedido;
   - se respetan los finales de línea de cada archivo (algunos usan CRLF, como `tests/test_pure.py` y `.gitignore`).
4. Si el cambio toca la interfaz, pedirle al usuario que lo pruebe con `streamlit run app.py` e indicarle qué página y tarjeta mirar.
5. Si cambió el comportamiento de una sección, actualizar `CLAUDE.md` y `README.md`.
6. Resumir en 2-4 líneas qué cambió y qué quedó pendiente de probar.
