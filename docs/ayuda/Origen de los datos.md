## Consultas de WhatsApp

Al terminar cada conversación, el asistente de WhatsApp registra un resumen. La aplicación toma esos registros y agrega:

- Provincia: se deduce de la característica del teléfono. Los números de otros países figuran como "Extranjero" y los que no tienen una característica reconocible, como "Sin identificar". La característica 11 (Ciudad de Buenos Aires y Gran Buenos Aires) se cuenta dentro de Buenos Aires.
- Área de interés: área a la que el asistente derivó la conversación (Máquinas, Repuestos o Servicio Técnico). Si no se puede determinar, figura como "No identificado".

Si una persona escribe varias veces en el mismo mes, sus conversaciones se agrupan y cuenta como una sola consulta. En el detalle se pueden leer todos los resúmenes.

Los números de prueba o internos se excluyen para que no se cuenten como consultas.

## Clasificación interna

Cada consulta recibe una clasificación que indica su calidad real.

| Clasificación | Significado |
|---|---|
| DERIVADO A BITRIX | Interés real en maquinaria; se derivó a un asesor comercial. |
| VENTA DE REPUESTOS | Terminó en una venta de repuestos. |
| DERIVADO A TÉCNICA | Consulta real de servicio técnico. |
| DERIVADO A RRHH | Búsqueda laboral, propuestas comerciales y similares. |
| NECESIDAD INCOMPATIBLE | Necesidad real que Cotear no cubre. |
| SIN RESPUESTAS | La persona dejó de responder. |
| SIN INTERES | Sin intención de compra; suelen ser ofrecimientos de servicios o mensajes no deseados. |
| SIN CLASIFICAR | Consulta que todavía no se revisó. |

SIN RESPUESTAS y SIN INTERES se agrupan como "sin interés real".

### Clasificación automática

Algunas consultas se clasifican solas:

- Números de otros países: SIN INTERES.
- Teléfonos que ya figuran en un negocio de Bitrix24: DERIVADO A BITRIX. El nombre del contacto se reemplaza por el registrado en Bitrix24.
- Consultas que el asistente identificó como técnicas: DERIVADO A TÉCNICA.

El resto queda SIN CLASIFICAR hasta que se revise en [[Clasificación manual]]. Una clasificación hecha a mano siempre prevalece sobre la automática.

## Negocios de Bitrix24

Se toman los negocios del pipeline de venta de máquinas, con su etapa actual y la anterior, las fechas de creación y del último movimiento, el cliente, la empresa, el teléfono, la fuente y el motivo de baja.

El tipo de máquina se obtiene del nombre del negocio. Se reconocen las variantes más comunes; por ejemplo, "centro de torneado" se cuenta como Torno CNC y "VMC" como Centro de mecanizado. Si el nombre no menciona la máquina, el negocio queda como "Otro / Sin clasificar". La lista completa está en [[Tipos de máquina]].

Las fuentes y los motivos de baja escritos de distintas formas se cuentan juntos, y cada uno conserva el mismo color en todos los gráficos.
