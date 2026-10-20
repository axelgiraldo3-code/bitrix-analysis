# COTEAR — Informe de Actividad Comercial

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
  sheets.py                 gspread I/O (fuente, pestañas mensuales, índice de teléfonos)
  bitrix.py                 Cliente REST Bitrix24 (batch, rate limit) + normalización de deals
  phone_ar.py               Formato '+54 9 <area> <local>' y provincia por código de área
  geo.py                    Conteo por provincia con agrupación en "Otros"
  cache.py                  Limpieza, unificación mensual, reglas automáticas, áreas
  machinery.py              Clasificación de maquinaria por nombre del negocio
  pending.py                Cola de clasificaciones sin sincronizar
  periods.py                Rangos de mes / trimestre / año
  branding.py, styling.py   Colores Cotear y coloreo de tablas
data/
  codigos_area_argentina.json   Código de área → provincia
  provincias_argentina.geojson  Contornos de provincias para el mapa (CABA dentro de Buenos Aires)
scripts/                    Diagnóstico de Bitrix y creación del libro destino
tests/                      Pruebas de funciones puras (pytest)
.streamlit/
  config.toml               Tema visual (azul #01498E)
  secrets.toml              (NO commitear)
```

## Tabs

- **Reporte mensual**: indicadores (provincia y área principal, % sin
  interés real = sin respuestas + sin interés), torta por clasificación, barras área de interés ×
  clasificación, mapa por provincia y tabla de consultas con su negocio de Bitrix.
- **Negocios Bitrix24**: período libre (mes, trimestre, año, rango). Sólo
  cuenta los negocios **creados** dentro del período (con su etapa actual); los
  movimientos de negocios de períodos anteriores no se incluyen. KPIs,
  barras tipo de máquina × etapa (% o cantidad) con su tabla, motivos de baja,
  mapa por provincia y lista de negocios con etapa anterior (columna
  Tipo maquinaria opcional).
- **Clasificación Manual**: selección de un reporte y guardado en cola; el
  botón *Sincronizar* del sidebar lo escribe en Sheets.

## Reglas automáticas de clasificación

Se aplican al cargar los reportes del mes:

- Todos los reportes de un mismo número dentro del mismo mes calendario se
  **unifican** sobre el último (los resúmenes previos quedan debajo).
- Número extranjero → `SIN INTERES`.
- Teléfono presente en algún negocio de venta de Bitrix → `DERIVADO A BITRIX`,
  y el nombre se reemplaza por el de Bitrix. El cruce usa el índice
  `_bitrix_telefonos` (todos los negocios, refresco semanal) más los negocios
  del mes.
- `Tipo de contacto = SI_RESUMEN_G2` → `DERIVADO A TÉCNICA`.
- Resto → `SIN CLASIFICAR` (placeholder: no se guarda en Sheets, así una
  coincidencia posterior con Bitrix lo reclasifica sola).

La clasificación manual sobrescribe cualquier valor previo y persiste en la
pestaña `YYYY-MM_Bot` del libro destino; sólo se escriben las filas que cambian.

## Tests

```
pip install -r requirements-dev.txt
pytest
```
