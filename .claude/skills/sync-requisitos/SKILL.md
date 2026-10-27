---
name: sync-requisitos
description: Actualiza los requisitos (CLAUDE.md o .claude/rules/), el README y la nota de Ayuda cuando cambia un requisito o el comportamiento de una sección de la app.
---

1. Identificar dónde está descripto lo que cambió:
   - detalle de una página, tarjeta o módulo: el archivo de `.claude/rules/` correspondiente (cada uno indica en `paths:` qué archivos cubre);
   - reglas generales, arquitectura, estilo o convenciones: `CLAUDE.md`.
2. Editar sólo esas líneas, con el mismo estilo: qué muestra, selector si tiene y qué columnas trae en Datos.
3. Si cambia la descripción de una página o tarjeta, ajustar también `README.md` y la nota de `docs/ayuda/` de esa sección (español neutro, sin términos técnicos).
4. Si se agrega un módulo o archivo nuevo, sumarlo a `paths:` de la regla que corresponda.
