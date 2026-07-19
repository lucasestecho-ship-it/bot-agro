# Capataz Campo - Entregables que hace la cuadrilla

Esta version distingue una nota o recordatorio de un trabajo profesional. Cuando Lucas pide un informe, una propuesta, un presupuesto o una comparacion, Capataz selecciona un contrato de entrega, ejecuta los especialistas, pasa por Contralor y devuelve archivos PDF y DOCX.

## Como pedirlos

No hay formularios obligatorios. Se puede escribir o mandar audio, PDF, Word, Excel, CSV, fotos o paquetes geoespaciales desde Telegram. Ejemplos:

- `Compara estos tres presupuestos. Normaliza IVA, flete, moneda y cantidades. Devolveme PDF y Word.`
- `Arma una propuesta tecnica para La Susana. Inclui dos modalidades y deja pendientes los honorarios que no te di.`
- `Evalua la compra de esta isla contra La Tigra. La Tigra es referencia economica; no inventes el precio.`
- `Prepara un dossier tecnico para vender el campo, sin presentarlo como tasacion.`
- `Hacer proyecto de agua: demanda, reserva, red, bomba, alternativas y analisis economico.`

El comando `/informes` muestra el catalogo dentro de Telegram.

## Catalogo y responsables

| Entregable | Agentes principales | Resultado |
|---|---|---|
| Proyecto de agua | Aqua, Hidro, Topo, Margen, Informes, Contralor | Diagnostico, demanda, reserva, hidraulica, alternativas, economia y etapas |
| Propuesta tecnica/comercial | Comercial, Margen, Informes, Contralor | Objetivo, alcance, metodo, entregables, honorarios, condiciones y aceptacion |
| Presupuesto profesional | Comercial, Margen, Tero, Informes, Contralor | Detalle valorizado, totales recomponibles, forma de pago, vigencia y exclusiones |
| Comparativo de presupuestos | Tero, Margen, Comercial, Informes, Contralor | Ofertas homologadas, diferencias, faltantes, riesgo y recomendacion |
| Evaluacion de compra | Topo, Aqua, Margen, Tero, Informes, Contralor | Superficie util, productividad, agua, valor relativo, riesgo y regla de decision |
| Comparacion de campos/islas | Topo, Aqua, Margen, Tero, Informes, Contralor | Base metodologica comun, brechas, sensibilidad y limites economicos |
| Dossier para venta | Comercial, Topo, Aqua, Margen, Informes, Contralor | Ficha verificable, mapas, mejoras, oportunidades, condicionantes y contacto |
| Informe de recorrida | Cartera, Informes, Margen, Contralor | Evidencias, diagnostico, compromisos, prioridades y proxima visita |
| Informe tecnico agronomico | Especialista aplicable, Margen, Informes, Contralor | Resultados, diagnostico, alternativas, economia y plan de implementacion |

## Reglas que no se pueden saltear

1. Todo numero conserva unidad, fecha y fuente.
2. Se separa lo medido/provisto, lo calculado, lo inferido y lo pendiente.
3. Los calculos deben mostrar formula y operandos. Si falta un dato, el resultado queda pendiente.
4. Margen informa inversion, costo anual, impacto productivo, margen adicional, equilibrio, repago, caja y sensibilidad cuando existan datos.
5. Contralor bloquea precios inventados, totales no recomponibles, comparaciones no homologadas y conclusiones definitivas sin evidencia.
6. El PDF y el Word llevan la identidad profesional de Lucas y sus fuentes.
7. Generar un borrador o informe no autoriza enviarlo ni comprometer precio, plazo u obra. El correo solo se envia mediante confirmacion expresa.

## Criterios heredados de los trabajos anteriores

- Propuestas: objetivo claro; gabinete, campo y analisis posterior; herramientas; entregables; modalidades; honorarios; forma de pago; exclusiones; proximo paso y aceptacion.
- Agua: demanda extrema y por etapas, fuente sostenible, autonomia, escenarios de corte, radios de caminata, cotas, perdidas de carga, bomba, computo, CAPEX y pendientes de campo.
- Compra y comparacion de islas: no confundir referencia tecnica con economica; comparar sobre una base comun; informar hectareas brutas/utiles; usar rangos y sensibilidad; condicionar la decision a acceso, evacuacion, infraestructura y verificacion legal.
- Presupuestos de proveedores: homologar marca/modelo, cantidad, unidad, moneda, IVA, descuento, flete, plazo, garantia y faltantes antes de comparar el total.
- Venta de campo: comunicar ventajas con respaldo y mostrar condicionantes materiales; no transformar un dossier tecnico en tasacion o estudio dominial.

## Archivos y almacenamiento

Los originales y entregables se registran como activos del evento. Si Supabase esta configurado se suben para trazabilidad; el archivador de Windows puede copiarlos y eliminarlos de Supabase solo despues de verificar la descarga. Los archivos locales de Render son transitorios y no se consideran archivo definitivo.
