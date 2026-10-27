---
name: commit-pr
description: Commitea los cambios probados con rama, Pull Request y merge a main en el mismo paso. Usar sólo cuando el usuario pida commitear.
disable-model-invocation: true
---

Sólo cuando el usuario lo pide y los cambios ya están probados.

1. Correr `/verificar` (ruff y pytest en verde). Si falla, frenar y avisar.
2. `git status` y `git diff --stat`: mostrar al usuario qué entra en el commit. Los cambios ajenos al pedido (otros archivos modificados que ya estaban) no se mezclan: preguntar. Nunca incluir `.streamlit/secrets.toml`, `credentials.json`, `CLAUDE.md` ni archivos de `data/` con contactos.
3. Desde `main` actualizado (`git fetch` + `git pull`), crear una rama con nombre descriptivo: `feat/...`, `fix/...` o `refactor/...`.
4. Agregar los archivos por nombre (no `git add -A`) y commitear con un mensaje claro en español, estilo `feat: barras por día de la semana en Reporte mensual`. Si hay grupos de cambios distintos, un commit por grupo.
5. `git push -u origin <rama>`.
6. `gh pr create` con título y una descripción breve de qué cambia y cómo se probó.
7. `gh pr merge --merge --delete-branch` (merge común: los commits por grupo se conservan en `main`), volver a `main` y `git pull`.
8. Confirmar al usuario el link del PR y que Streamlit Cloud va a redeployar desde `main`.
