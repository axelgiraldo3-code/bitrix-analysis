# COTEAR — App de análisis de consultas y negociaciones

Aplicación Streamlit para analizar los reportes del bot de WhatsApp
(Neurolinks) y las negociaciones de Bitrix24 de Cotear SRL.

## Setup local

1. Crear entorno virtual e instalar dependencias:
   ```
   python -m venv .venv
   .venv\Scripts\activate            # Windows
   pip install -r requirements.txt
   ```
2. Completar `.streamlit/secrets.toml` (ver `secrets.example.toml`).
3. Crear el libro de destino (una vez):
   ```
   python -m scripts.create_destination_sheet "COTEAR - Persistencia"
   ```
   Pegar el `spreadsheet_id` que imprime en la sección `[google_sheets.dest]`
   del `secrets.toml`.
4. Ejecutar:
   ```
   streamlit run app.py
   ```

## Estructura

```
app.py                      Punto de entrada Streamlit (3 tabs)
utils/
  sheets.py                 gspread I/O (fuente y destino, pestañas mensuales)
  bitrix.py                 Cliente REST Bitrix24 + normalización de deals
  phone_ar.py               Formateo AR '+54 9 (XXX) XXXX-XXXX'
  cache.py                  Limpieza, unificación <2 días y reglas automáticas
  machinery.py              Clasificación de maquinaria por nombre
  branding.py               Colores/paletas Cotear
data/
  codigos_area_argentina.json
scripts/
  create_destination_sheet.py
.streamlit/
  config.toml               Tema visual (azul #01498E)
  secrets.toml              (NO commitear)
```

## Reglas automáticas de clasificación

Se aplican al cargar los reportes:

- Reportes con menos de 2 días de diferencia entre sí se **unifican** sobre el
  último (más completo).
- Número extranjero → `SIN INTERES`.
- `Tipo de contacto = SI_RESUMEN_G2` → `DERIVADO A TÉCNICA`.
- Teléfono con match en Bitrix → `DERIVADO A BITRIX`, y el nombre se
  reemplaza por el que figura en Bitrix.
- Resto → `SIN CLASIFICAR`.

La clasificación manual (Tab 1) sobrescribe cualquier valor previo y persiste
en la pestaña `YYYY-MM_Bot` del libro destino.
