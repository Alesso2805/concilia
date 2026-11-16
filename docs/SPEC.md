# Concilia — Especificación

Historias: docs/BACKLOG.md.

## Visión y objetivo

Concilia (nombre de código; paquete `concilia`) es un backoffice web que cruza el extracto bancario de una empresa con sus cobros esperados (facturas o cuentas por cobrar) y deja a la vista qué está conciliado, qué falta, qué está duplicado y qué no cuadra. Un asistente de IA explica diferencias y sugiere coincidencias, pero nunca decide: un analista confirma y un revisor distinto aprueba, y todo queda en un historial que no se puede editar.

**El problema.** En las pymes y en los equipos de finanzas de empresas medianas, la conciliación bancaria se hace en Excel: se descarga el extracto, se busca cada abono a mano en la lista de facturas y se marcan colores. Es lento, depende de una persona y no deja rastro de quién decidió qué. Los errores típicos son:

- un abono que paga varias facturas, o una factura pagada en dos abonos;
- montos que no cuadran por comisiones, detracciones o redondeos;
- referencias escritas de cualquier forma ("PAGO FACT F001-123", "transf. cliente ABC");
- el mismo extracto importado dos veces.

**Qué demuestra.** Concilia es un proyecto de portafolio que muestra, en un sistema completo y desplegado, lo que se construye en proyectos empresariales:

| Capacidad | Cómo se ve en Concilia |
| --- | --- |
| Frontend empresarial con Angular moderno | Componentes standalone, signals, control de flujo nativo, formularios reactivos tipados, RxJS donde corresponde, sin zone.js |
| Sistemas de backoffice | Roles, aprobación en dos pasos (maker-checker), auditoría, multiempresa con aislamiento en la base, procesos en segundo plano, reportes en Excel |
| IA aplicada con control | La IA sugiere con salida estructurada validada, cada sugerencia se acepta o rechaza con trazabilidad, y el sistema funciona igual sin IA |

**Qué no es.** No se conecta a bancos ni a SUNAT, no mueve dinero y no reemplaza a un contador. Trabaja con archivos CSV o Excel que el usuario sube.

**Usuarios.**

- **Analista de cobranzas o tesorería:** importa extractos y cobros, revisa propuestas, pide sugerencias a la IA y confirma conciliaciones.
- **Revisor (jefe de finanzas):** aprueba o rechaza lo confirmado, revierte si hace falta y cierra el período.
- **Administrador de la empresa:** invita usuarios, asigna roles y configura cuentas, formatos de importación y tolerancias.
- **Visitante de la demo:** entra a una demo pública propia, con datos ficticios, sin registrarse.

**Cómo se mide el éxito.**

- Demo pública desplegada: cada visitante recibe su propia organización de demo con datos ficticios.
- Con el dataset de demo (500 movimientos, 400 cobros), el motor propone con las reglas R1 a R3 coincidencias correctas para al menos el 70 % de los abonos, y con las demás reglas y las sugerencias aceptadas se supera el 90 %.
- README en inglés con arquitectura, decisiones (ADR), cómo correrlo y un video corto.

## Alcance del MVP y funcionalidades

El MVP cubre el ciclo completo de una conciliación mensual para una empresa en soles, desde la importación hasta el cierre del período, con una demo pública.

| Área | Funcionalidad | Detalle |
| --- | --- | --- |
| Acceso | Cuentas y sesiones | Inicio de sesión con correo y contraseña; sesión por cookie; elección de organización. El registro abierto se activa con `REGISTRATION_ENABLED` y está apagado en la instancia pública; ahí las organizaciones reales se crean con `make create-org` |
| Acceso | Equipo y roles | Invitación por enlace; roles `admin`, `analyst`, `reviewer`; una persona puede tener varios roles, pero nunca aprueba ni rechaza lo que ella misma creó o confirmó; baja de miembros |
| Configuración | Organización | Tolerancia de diferencias y tasas de detracción |
| Datos | Cuentas bancarias | Banco, moneda (solo PEN en el MVP), alias y últimos 4 dígitos |
| Importación | Perfiles | Mapeo de columnas por tipo de archivo (extracto o cobros); plantillas de ejemplo para BCP, Interbank y BBVA que se copian al crear un perfil |
| Importación | Extractos bancarios | CSV o XLSX; vista previa antes de confirmar; detección de archivo y de movimientos ya importados; descartar una vista previa; anular una importación |
| Importación | Cobros esperados | CSV o XLSX de facturas o cuentas por cobrar: cliente, RUC opcional, número de documento, emisión, vencimiento y monto; anular un cobro |
| Conciliación | Motor de reglas | Reglas R1 a R6 con puntaje y explicación; corre en segundo plano sobre una cuenta y un período abiertos |
| Conciliación | Flujo de aprobación | El analista confirma o descarta; un revisor distinto aprueba o rechaza; un revisor puede revertir una aprobada mientras el período esté abierto |
| Conciliación | Manual y en lote | Conciliación manual con suma y diferencia en vivo; confirmar y aprobar en lote las de puntaje 100 |
| Conciliación | Diferencias | Diferencia con motivo (comisión, detracción, redondeo, sobrepago, otro) y pagos parciales |
| IA | Sugerencias | Para un abono sin conciliar, la IA propone candidatos con su razón; el servidor valida y recalcula; el analista acepta o rechaza |
| Períodos | Cierre mensual | Un revisor cierra el período cuando no quedan coincidencias propuestas ni confirmadas; reabrir exige motivo |
| Reportes | Panel y exportación | Porcentaje conciliado, pendientes por antigüedad (medida contra el último día del período, o contra hoy si es el mes en curso) y diferencias por motivo; exportación a Excel del período |
| Auditoría | Historial | Quién importó, confirmó, aprobó, rechazó, revirtió, cerró o aceptó una sugerencia, y cuándo |
| Demo | Organización propia por visitante | Botón "Probar la demo" que crea una organización con datos ficticios y usuarios por rol, archivos de ejemplo descargables y recorrido guiado; se borra a las 4 horas |

**El ciclo de uso.**

1. El administrador registra una cuenta bancaria, crea los perfiles de importación e invita a un analista y a un revisor.
2. El analista importa el extracto del mes y la lista de cobros.
3. El analista corre el motor, que propone coincidencias con su puntaje.
4. El analista revisa, confirma o descarta, concilia a mano lo que faltó y pide ayuda a la IA para los abonos sin propuesta.
5. El revisor aprueba o rechaza lo confirmado y cierra el período.
6. Se exporta el reporte del mes a Excel.

**Fuera del MVP** (en orden de prioridad):

- Moneda extranjera y tipo de cambio.
- Conectores con bancos o con sistemas contables (ERP).
- Reglas de conciliación definidas por el usuario.
- Conciliar cargos del extracto (pagos a proveedores).
- Inicio de sesión con Google o Microsoft (SSO).

## Arquitectura y stack

Un monolito modular con dos procesos (API y worker) que comparten código y base de datos, y un frontend Angular servido como archivos estáticos por Caddy.

| Pieza | Tecnología | Responsabilidad |
| --- | --- | --- |
| `web` | Angular, servido por Caddy | Interfaz del analista, el revisor y el administrador; entrada y recorrido de la demo |
| `concilia.api` | FastAPI + Uvicorn | API REST bajo `/api`, sesiones, validación, encolar trabajos |
| `concilia.worker` | Proceso Python con el mismo código y rol `concilia_worker` | Ejecutar trabajos de la cola (importaciones, motor, IA, exportaciones) y el planificador de tareas periódicas |
| PostgreSQL 17 | RLS por organización | Datos, cola de trabajos y archivos (`bytea`, hasta 5 MB) |
| Proveedor de IA | API externa detrás del puerto `LlmClient` | Sugerencias con salida estructurada |
| Caddy | Proxy inverso | HTTPS, archivos estáticos, cabeceras de seguridad, límite de 6 MB por petición |

**Por qué los archivos van en PostgreSQL.** Son pocos, pequeños y se procesan una vez; guardarlos en la base evita un servicio más y simplifica el borrado de las demos. El ADR-0004 describe cómo moverlos a S3 si el proyecto creciera.

**Módulos del backend.** Cada uno tiene las capas `domain`, `application`, `infrastructure` y `api`. El dominio no importa FastAPI, SQLAlchemy ni httpx. Un módulo solo usa a otro a través de su capa `application` y solo importa a los que están antes en este orden (import-linter lo verifica):

| Orden | Módulo | Contenido |
| --- | --- | --- |
| 0 | `shared.kernel` | `Clock`, `Money`, ids, errores base y normalización de textos y números de documento; puro, sin dependencias |
| 1 | `shared.infrastructure` | Sesión de base, contextos de acceso, cola de trabajos, settings, logging; puede importar `shared.kernel` |
| 2 | `audit` | Registro de eventos de auditoría |
| 3 | `identity` | Usuarios, sesiones, organizaciones, membresías, roles, invitaciones, configuración de la organización |
| 4 | `banking` | Cuentas bancarias, perfiles de importación y plantillas de bancos |
| 5 | `periods` | Estado de los períodos, cierre y reapertura |
| 6 | `imports` | Archivos, vista previa, movimientos bancarios y cobros esperados |
| 7 | `matching` | Motor (función pura), coincidencias, decisiones, diferencias y saldos |
| 8 | `ai` | Puerto `LlmClient`, prompts versionados, sugerencias y su aceptación |
| 9 | `reporting` | Panel y exportación a Excel |
| 10 | `demo` | Generador de datos ficticios, archivos de ejemplo y creación de demos |

**Puertos hacia módulos posteriores.** Cuando un módulo necesita saber algo de uno posterior, define un puerto en su capa `application` y el módulo posterior lo implementa. El cableado vive solo en `api.py` y `worker.py`. Los puertos del MVP son:

- `periods.PendingMatchesQuery` (lo implementa `matching`): ¿quedan coincidencias propuestas o confirmadas en este período?
- `imports.ActiveMatchesQuery` (lo implementa `matching`): ¿cuáles de estos movimientos o cobros están en coincidencias activas (propuestas, confirmadas o aprobadas), y cuáles solo en propuestas o confirmadas?

Desde CN-12 ambos los implementa `matching.infrastructure.SqlMatchQueries`; antes se cableaban con un adaptador que respondía "no hay coincidencias".

**Frontend.** Carpetas por funcionalidad: `features/auth` (inicio de sesión, aceptar invitación, registro), `features/admin` (equipo, configuración, cuentas y perfiles), `features/imports`, `features/matching` (bandeja, manual, lotes), `features/ai`, `features/periods`, `features/reports` (panel y exportación), `features/audit` y `features/demo`. Cada una con rutas diferidas (lazy). Estado de la pantalla con signals; un servicio por funcionalidad que envuelve los servicios generados desde OpenAPI. Las tablas usan `mat-table` con `mat-paginator` y paginación del servidor por keyset (sin scroll virtual): solo anterior y siguiente, sin total ni salto a la última página, con un cursor compuesto por el orden activo más el id, que se reinicia al cambiar filtros o pestaña. Las fuentes e íconos de Material se sirven desde la propia app (sin Google Fonts). Un interceptor redirige al inicio de sesión ante un 401 y muestra un aviso ante un 403.

**Seguimiento de trabajos en la interfaz.** Al encolar, la API devuelve el id del trabajo. La interfaz consulta su estado cada 2 segundos con un `interval` + `switchMap` que se detiene en `done` o `failed`, se cancela al salir de la ruta (`takeUntilDestroyed`) y se rinde a los 5 minutos con un mensaje.

**Sesiones y CSRF.** Cookie `__Host-concilia_session` httpOnly, Secure, SameSite=Lax, con identificador opaco guardado como hash; vence a las 12 horas sin uso o a los 7 días. CSRF con doble envío firmado: con sesión, la API pone una cookie legible `__Host-XSRF-TOKEN` con un HMAC del id de sesión, y Angular la devuelve en la cabecera `X-XSRF-TOKEN` con `withXsrfConfiguration` (`cookieName` ajustado). Las rutas `/api/public/*` (inicio de sesión, aceptar invitación, registro, crear demo) no usan el token: exigen que la cabecera `Origin` sea la del sitio y se apoyan en SameSite. **Cambio de rol en la demo:** `POST /api/app/demo/switch-role {role}` solo si la organización es de demo, no venció y el usuario actual y el destino son usuarios de demo de esa misma organización; revoca la sesión actual y emite una nueva con su token CSRF; queda en la auditoría. Sin JWT. Límite de intentos de inicio de sesión por IP y por correo. La IP real llega desde Caddy: Uvicorn corre con `--proxy-headers` y `--forwarded-allow-ips` limitado a la red de Caddy, y Caddy sobrescribe `X-Forwarded-For`. En local se usa `https://localhost` con `tls internal` de Caddy (una sola vez, `make trust-ca` instala su CA en el almacén del sistema para que el navegador la acepte), y los tests usan `base_url="https://test"`, así las cookies `__Host-` funcionan igual que en producción.

**Cola de trabajos.** Tabla `jobs` con tipo, organización (nula en tareas del sistema), carga, estado, progreso, intentos, `run_after` y `dedup_key`. Cada trabajo usa tres transacciones separadas:

1. Tomar: `SELECT ... FOR UPDATE SKIP LOCKED`, pasar a `running`, sumar un intento y fijar `locked_at`.
2. Trabajar: en su propia transacción (el progreso se actualiza en transacciones cortas aparte).
3. Cerrar: `done`, o de vuelta a `queued` con espera creciente si quedan intentos (máximo 3), o `failed` con un código de error.

Mientras trabaja, el worker mantiene `pg_advisory_lock` sobre el id del trabajo en su conexión dedicada. Un trabajo en `running` con `locked_at` de hace más de 10 minutos vuelve a la cola (o pasa a `failed` si agotó los intentos) solo si ese bloqueo está libre. Cada trabajo es idempotente: los resultados guardan `job_id` con `UNIQUE (job_id)` (`engine_runs`, `ai_suggestions`, `exports`) y la transacción de trabajo comprueba primero si ya existe; `confirm_import` no hace nada si el archivo ya está confirmado. Si la organización del trabajo ya no existe, pasa a `failed` sin reintentos.

**Planificador.** El worker revisa cada minuto qué tareas periódicas tocan y las encola con `dedup_key` para no duplicarlas. La única del MVP es `cleanup`, cada 15 minutos: llama a `app_cleanup(p_now)`, que borra exportaciones vencidas, descarta vistas previas abandonadas hace más de 24 horas y borra las organizaciones de demo vencidas. Cada parte la agrega la historia dueña de esos datos (CN-09, CN-18 y CN-22).

**Cabeceras de seguridad.** `script-src 'self'` (el build de Angular sin scripts en línea; el ADR-0007 verifica las opciones de CSP del build y del CSS crítico en línea), `style-src 'self' 'unsafe-inline'` documentado como excepción aceptada por los estilos que inyecta Angular, `frame-ancestors 'none'`, HSTS, `Referrer-Policy: no-referrer`. Se prueban contra la aplicación real en CN-06.

**Despliegue.** Un servidor pequeño con Docker Compose y Caddy, despliegue automático al fusionar en `main`, `pg_dump` diario con `concilia_backup` y `/api/health` con monitor externo. Costo objetivo: menos de US$ 10 al mes más la IA, con un tope de gasto configurado en el proveedor y el límite global diario de la aplicación.

## Reglas de negocio

El MVP concilia **abonos** (movimientos con monto positivo) contra **cobros esperados**. Los cargos del extracto se importan y se muestran, pero no se concilian.

**Glosario de saldos**

| Término | Definición |
| --- | --- |
| Coincidencia activa | Su estado es propuesta, confirmada o aprobada |
| Aplicado a un cobro | `applied_cents` de ese cobro en una coincidencia |
| Saldo abierto de un cobro | Monto − suma de lo aplicado en coincidencias **aprobadas**. Es lo que se reporta |
| Saldo disponible de un cobro | Saldo abierto − suma de lo aplicado en coincidencias **propuestas o confirmadas**. Es lo que puede usar el motor, la IA o una conciliación manual |
| Abono libre | Abono no anulado que no está en ninguna coincidencia activa |

Un cobro anulado (`cancelled_at`) no es candidato. Ningún saldo disponible puede quedar negativo: se valida bajo el bloqueo de la organización.

**Importación**

| Regla | Detalle |
| --- | --- |
| Perfiles | Un perfil es de tipo `bank_statement` (ligado a una cuenta bancaria) o `receivables` (de la organización). Define columnas, formato de fecha, separador decimal, signo o columnas separadas de cargo y abono, y filas a saltar. Las plantillas de BCP, Interbank y BBVA viven en código y se copian al crear un perfil; están marcadas "verificar con tu extracto real" |
| Estados de un archivo | `uploaded` → `parsing` → `previewed` o `failed`; de `previewed` a `confirmed` o `discarded`; de `confirmed` a `voided`. Una subida que no termina de leerse en 24 horas pasa a `failed` con el código `abandoned` |
| Vista previa | Muestra filas válidas, filas con error (con motivo), movimientos ya importados y filas de períodos cerrados; en cobros, si cada fila crea, actualiza (con el vencimiento y el monto anteriores), no cambia nada o está en conflicto. Nada se guarda como movimiento o cobro hasta confirmar. Una vista previa sin confirmar se descarta sola a las 24 horas |
| Archivo repetido | Al subir se avisa si hay otro archivo confirmado del mismo tipo con el mismo SHA-256 en la misma cuenta (en la organización, si es de cobros); al confirmar se rechaza. Un archivo descartado, fallido o anulado no bloquea volver a subirlo |
| Huella del movimiento | Hash de (cuenta, fecha, monto, descripción normalizada, número de operación si existe, índice de aparición de esa misma combinación dentro del archivo). Única por cuenta entre movimientos no anulados: dos filas idénticas en un archivo son válidas; la misma fila en otro archivo es un repetido y se omite |
| Perfil usado | Al subir el archivo se guardan `import_profile_id` y una copia del perfil (`profile_snapshot`); la vista previa y la confirmación usan solo esa copia |
| Confirmar | Guarda las filas válidas que no son repetidas ni de un período cerrado |
| Anular un extracto | Solo si ninguno de sus movimientos está en una coincidencia activa y ninguno cae en un período cerrado. Marca sus movimientos como anulados (`voided_at`) |
| Cobros esperados | Clave única por organización: número de documento normalizado; un documento repetido dentro del mismo archivo es una fila con error. El RUC es opcional y, si viene, tiene 8 u 11 dígitos (DNI o RUC). Al reimportar un cobro existente: si está anulado, la fila es un conflicto; si trae el mismo vencimiento y monto, no cambia nada; si cambian, se actualizan solo si no está en ninguna coincidencia activa, y si lo está, la fila es un conflicto |
| Anular un cobro | El analista lo anula con motivo si no está en coincidencias propuestas ni confirmadas; lo ya aprobado se conserva y el resto deja de figurar como pendiente. Anular una importación de cobros anula los cobros que creó, con la misma condición para todos |

**Normalización** (en `shared.kernel`). Textos: mayúsculas, sin tildes, solo letras, dígitos y espacios simples. Número de documento: se acepta `SSSS-NNNNNNNN`, donde la serie tiene 4 caracteres que empiezan con letra; la forma corta `L` + 1 a 3 dígitos se completa con ceros a 3 dígitos (`F1` → `F001`). El número va sin ceros a la izquierda. Así, `F001-00000123`, `F1-123` y `f001-123` se convierten en `F001-123`. Los números de documento de un movimiento (`doc_refs`) se extraen de la descripción **original** pasada a mayúsculas y sin tildes, antes de quitar signos, con `\b([A-Z][A-Z0-9]{3}|[A-Z]\d{1,3})\s*-\s*0*(\d{1,8})\b`, y cada resultado se normaliza con la misma función que `doc_number_norm`.

**Clientes y similitud.** Un cliente se identifica por `customer_tax_id` si existe y, si no, por `customer_name_norm`. Para comparar, al nombre normalizado se le quitan los sufijos societarios (SAC, SA, SAA, SRL, EIRL, SCRL) y las palabras de menos de 3 letras. Similitud de un cliente con un abono:
- 100 si su RUC aparece en la descripción;
- si el nombre filtrado tiene 2 o más palabras, `rapidfuzz.fuzz.token_set_ratio` entre el nombre filtrado y la descripción normalizada;
- si tiene una sola palabra, 100 si esa palabra de 5 o más letras aparece completa en la descripción y 0 si no;
- 0 si el nombre filtrado queda vacío.

**Motor de conciliación.** Corre sobre los abonos libres y los cobros con saldo disponible de una cuenta y un período abiertos. Las reglas se aplican en este orden, cada una sobre todos los abonos antes de pasar a la siguiente; dentro de cada regla, los candidatos se ordenan por puntaje, luego por fecha del abono y luego por id, salvo R5, que recorre los cobros por vencimiento ascendente y luego por id. Un abono o un cobro que entró en una propuesta de esta corrida no se vuelve a usar en ella.

| # | Regla | Condición | Puntaje | Aplicado y diferencia |
| --- | --- | --- | --- | --- |
| R1 | Exacta | La descripción contiene el número de documento y el abono es igual al saldo disponible | 100 | Aplicado = abono; diferencia 0 |
| R2 | Varios documentos en un abono | La descripción contiene dos o más números de documento y la suma de sus saldos disponibles es igual al abono | 95 | Cada uno su saldo; diferencia 0 |
| R3 | Referencia con diferencia | La descripción contiene el número de documento y la diferencia está dentro de la tolerancia o coincide con una detracción | 85 | Aplicado = saldo disponible; diferencia = abono − saldo, con motivo sugerido |
| R4 | Mismo cliente, varios cobros | El cliente con mayor similitud con el abono (≥ 85; si hay empate, no se propone) tiene exactamente una combinación de 2 a 4 cobros que suma el abono | 80 | Cada uno su saldo; diferencia 0 |
| R5 | Cobro pagado en partes | Exactamente una combinación de 2 a 3 abonos libres del mismo período, con similitud ≥ 85 al cliente, todos entre la emisión y 30 días después del vencimiento y con como máximo 30 días entre el primero y el último, suma el saldo disponible | 75 | Aplicado = saldo; diferencia 0 |
| R6 | Monto y fecha | Abono igual al saldo disponible, fecha entre la emisión y 30 días después del vencimiento, y un único candidato; +15 si la similitud de cliente es ≥ 85 | 60 o 75 | Aplicado = abono; diferencia 0 |

- **Límites de búsqueda:** R4 considera como máximo los 10 cobros con saldo disponible del cliente cuyo vencimiento está más cerca de la fecha del abono (hasta 375 combinaciones de 2 a 4). R5 considera como máximo los 12 abonos candidatos cuya fecha está más cerca del vencimiento del cobro (hasta 286 combinaciones de 2 a 3). A igual distancia gana la fecha más antigua y luego el id. Se mantiene un tope de seguridad de 500 combinaciones por abono (R4) o por cobro (R5): si se alcanza, la regla no propone nada para ese caso.
- No se crean propuestas con puntaje menor a 60. Si R4, R5 o R6 encuentran más de una combinación (o más de un candidato) que cumple la regla, no proponen nada para ese caso y esos abonos quedan como candidatos para la IA.
- **Varios documentos en la descripción:** R1 y R3 proponen solo si exactamente uno de los documentos mencionados cumple la condición; los números que no corresponden a un cobro con saldo disponible se ignoran. R2, en cambio, exige que todos los documentos mencionados sean cobros con saldo disponible.
- **Único candidato en R6:** el abono tiene un solo cobro candidato y ese cobro es candidato solo de ese abono. Si dos abonos compiten por el mismo cobro, ninguno recibe propuesta.
- **Similitud de un cliente en R4, R5 y R6:** es la mayor entre los nombres de sus cobros (un cliente identificado por RUC puede tener nombres distintos). En R4, el cliente de mayor similitud y los empates se buscan entre todos los clientes de los cobros de la corrida, aunque sus cobros ya se hayan usado en ella.
- **Motivo sugerido en R3:** si la diferencia cabe en la tolerancia, el motivo es `rounding`, aunque también coincida con una detracción; si coinciden varias tasas, se usa la de menor residuo y, a igual residuo, la tasa menor. Si la diferencia es 0 (R1 no pudo decidir porque había dos documentos exactos y otra regla usó uno), no hay motivo.
- El motor no vuelve a proponer, en el mismo período, una combinación exacta de abonos y cobros que ya fue descartada, rechazada o revertida. Cada regla elige su resultado sin mirar esas combinaciones; si el resultado es una de ellas, la regla no propone nada para ese caso (no pasa a otra combinación) y el abono sigue disponible para las reglas siguientes.
- **Tolerancia:** la diferencia está dentro de la tolerancia si su valor absoluto es menor o igual que el mayor entre `tolerance_min_cents` (100 por defecto) y `tolerance_bp` del saldo (50 = 0.5 % por defecto, redondeado a céntimos hacia abajo). Motivo sugerido: `rounding`.
- **Detracción:** para cada tasa configurada (por defecto 10 % y 12 %), detracción = saldo × tasa, redondeada al sol entero (mitad hacia arriba). Coincide si `|abono − (saldo − detracción)| ≤ 100` céntimos. Motivo sugerido: `detraction`.
- Cada propuesta guarda la regla, el puntaje, el motivo sugerido y una explicación por plantilla (por ejemplo: "La descripción menciona F001-123 y el monto coincide").
- R5 solo ve abonos del período en que corre; un cobro pagado en partes en dos meses se concilia a mano (limitación del MVP).
- El motor no corre sobre un período cerrado.
- Una corrida se pide con el id del cliente para `engine_runs` y se procesa como trabajo `run_engine`; mientras otra corrida de la misma cuenta y mes esté en cola o en curso, la nueva se rechaza. Si el mes se cierra antes de que el trabajo empiece, el trabajo falla con `closed_period` sin proponer nada.

**Diferencias y pagos parciales.** En toda coincidencia: diferencia = suma de sus abonos − suma de lo aplicado. Cada aplicado es mayor que 0 y no supera el saldo disponible de su cobro.

- Si la diferencia no es 0, confirmar exige un motivo: `commission`, `detraction`, `rounding`, `overpayment` (solo si es positiva) u `other` (con nota).
- Un **pago parcial** no es una diferencia: es una coincidencia donde lo aplicado a un cobro es menor que su saldo disponible. El cobro queda abierto por el resto. La interfaz lo marca como "parcial".
- Las propuestas del motor siempre aplican el saldo completo; un pago parcial solo se crea a mano o desde una sugerencia de la IA.

**Estados de una coincidencia** (el último evento por `seq` define el estado; cada acción ocurre como máximo una vez por coincidencia):

| Desde | Acción | Hacia | Quién |
| --- | --- | --- | --- |
| (nueva) | crear | Propuesta | Motor (`created_by` nulo), analista a mano (queda además confirmada por él en la misma transacción) o analista al aceptar una sugerencia de IA |
| Propuesta | `confirm` | Confirmada | `analyst` |
| Propuesta | `discard` | Descartada | `analyst` |
| Confirmada | `approve` | Aprobada | `reviewer` distinto de quien la creó y de quien la confirmó |
| Confirmada | `reject` (con motivo) | Rechazada | `reviewer` distinto de quien la creó y de quien la confirmó |
| Aprobada | `revert` (con motivo) | Revertida | `reviewer` distinto de quien la creó y de quien la confirmó, solo si todos sus períodos están abiertos |

Descartada, rechazada y revertida son finales; sus abonos y cobros quedan libres. Las coincidencias de puntaje 100 se pueden confirmar en lote y aprobar en lote, siempre con dos personas distintas. El lote abarca una cuenta y un mes; la aprobación en lote deja para otra persona las que el revisor creó o confirmó, y la acción no lleva id del cliente porque repetirla no decide nada nuevo. Una coincidencia pertenece a los períodos de todos sus abonos; si cualquiera está cerrado, no admite acciones.

**Períodos.** Un período es un mes calendario por cuenta bancaria, según la fecha del movimiento. Está abierto hasta que un revisor lo cierra, y solo se cierra si no quedan coincidencias propuestas ni confirmadas con abonos de ese período y no es posterior al mes en curso (día de Lima). Cerrar y reabrir alternan (lo valida además un trigger bajo el bloqueo de la organización); reabrir exige motivo. En un período cerrado no se registran acciones, no se corre el motor y no se importan movimientos.

**Asistente de IA.**

1. El analista elige un abono libre y pide ayuda.
2. El servidor arma hasta 10 candidatos con saldo disponible, ordenados por cercanía de monto, similitud de cliente y fecha, y les asigna alias (`C1`…`C10`).
3. Al modelo se envían solo la fecha, el monto y la descripción del abono, y de cada candidato su alias, número de documento, nombre del cliente, saldo disponible, emisión y vencimiento.
4. El modelo responde con el esquema `{suggestions: [{candidates: ["C2", "C5"], applied: [{alias: "C2", cents}] | null, confidence: "low" | "medium" | "high", explanation, difference_reason: motivo | null}], no_match_reason: texto | null}` (hasta 3 sugerencias). Los campos opcionales van como nulos y `applied` es una lista de pares porque la salida estructurada estricta del proveedor exige todos los campos y no admite objetos con claves libres (ADR-0006).
5. El servidor descarta alias que no envió y aplicados que superen el saldo, **recalcula aplicados y diferencia** y los guarda con la sugerencia (`server_applied`), que es lo que muestra la interfaz. Si una sugerencia trae `applied` nulo o se descartó alguno: si la suma de los saldos disponibles de sus candidatos es menor o igual al abono, a cada uno se le aplica su saldo completo; si la supera, el abono se reparte por vencimiento ascendente y luego por número de documento, y el último recibe el resto como pago parcial. Si la salida no valida, se guarda con `valid = false` y no se muestra.
6. El analista acepta una sugerencia (se crea una coincidencia propuesta con origen `ai`) o la rechaza con motivo. Luego sigue el flujo normal.

**Límites de la IA.** Una consulta es un trabajo `ai_suggest` (con sus reintentos). Al encolar, bajo el bloqueo de la organización y un bloqueo global fijo, se cuentan los trabajos `ai_suggest` creados hoy (día de Lima), incluidos los que están en cola: como máximo 50 por organización y `AI_GLOBAL_DAILY_LIMIT` en toda la instancia (con `app_ai_usage_today`). Las organizaciones de demo no cuentan.

**Respuestas grabadas de la demo.** Las organizaciones de demo nunca llaman al proveedor real. Las grabaciones viven en el repo, indexadas por `dataset_version` y una clave estable del abono `(booked_on, amount_cents, description_norm, índice de aparición de esa combinación en el dataset)`, con los candidatos guardados por `doc_number_norm`, no por alias. Al reproducir, cada número de documento se traduce al cobro de esa demo y se aplican las mismas validaciones y el mismo recálculo; un candidato sin saldo disponible se descarta. Para un abono sin grabación, la respuesta es "sin sugerencias en la demo". Se graban con `make record-ai` sobre una organización normal (`is_demo = false`) de una base local cargada con el dataset de demo, con la clave real del proveedor tomada del entorno de quien graba, y un test falla si cambia `prompt_version` o `dataset_version` sin volver a grabar.

**Demo.**

- El botón "Probar la demo" crea una organización de demo con el generador determinista y fechas fijas por `dataset_version`: una cuenta bancaria, perfiles, tres usuarios de demo (`admin`, `analyst`, `reviewer`) y el extracto y los cobros de dos meses ya importados. El primer mes se concilia con el motor real (un `engine_runs` sin trabajo), lo confirma el analista y lo aprueba el revisor de la demo a través del dominio, y queda cerrado; el segundo queda sin conciliar. La precarga crece con las historias: desde CN-22, propuestas del motor; desde CN-14, confirmadas y aprobadas; desde CN-16, el período cerrado. La sesión entra como analista y un selector cambia de rol con el endpoint de cambio de rol.
- La demo ofrece para descargar un extracto CSV y un archivo de cobros de un tercer mes, con su perfil ya creado, para probar la importación. El extracto empieza con los tres últimos movimientos del mes anterior, como suele pasar al exportar del banco, y la vista previa los marca como ya importados.
- Además del botón, el enlace `/demo` crea una demo y entra en ella, para compartirlo.
- Se borra a las `DEMO_TTL_HOURS` horas (4 en producción). En local, `DEMO_TTL_HOURS=0` significa sin vencimiento: `demo_expires_at` se fija en 9999-12-31 00:00 UTC para cumplir el CHECK; cada «Probar la demo», o el enlace `/demo` que abre `make demo`, crea una nueva. Límite: 5 demos por IP al día y 300 por día en toda la instancia.

**Roles.**

| Acción | `admin` | `analyst` | `reviewer` |
| --- | --- | --- | --- |
| Invitar, asignar roles, dar de baja miembros, configurar la organización, cuentas y perfiles | Sí | No | No |
| Importar, descartar vistas previas, anular importaciones y cobros | No | Sí | No |
| Correr el motor, confirmar, descartar, conciliar a mano, confirmar en lote, usar la IA | No | Sí | No |
| Aprobar, rechazar, revertir, aprobar en lote, cerrar y reabrir períodos | No | No | Sí |
| Ver bandeja, panel, reportes y auditoría | Sí | Sí | Sí |
| Exportar a Excel | No | Sí | Sí |

La organización siempre conserva al menos un `admin` activo (validado bajo el bloqueo de la organización).

## Esquema de base de datos

PostgreSQL 17. Claves primarias uuid v7 generadas en la aplicación (o en el cliente, según la regla 11). Cada tabla de una organización tiene `UNIQUE (organization_id, id)` y las foráneas entre ellas son compuestas `(organization_id, x_id)`, para que ninguna fila apunte a otra organización; las excepciones son `memberships` y `member_roles`, cuya clave ya incluye `organization_id`. Los usuarios que crean o deciden algo se referencian con una foránea compuesta a `memberships (organization_id, user_id)`. Montos en `bigint` (céntimos). Los períodos son `date` con `CHECK (period = date_trunc('month', period)::date)`. Las tablas de eventos tienen `seq bigint GENERATED ALWAYS AS IDENTITY`.

**Tablas sin RLS (lista cerrada; el test de catálogo falla si aparece otra):** `users`, `sessions`, `rate_limits` y la tabla de versiones de Alembic. `jobs` tiene RLS con políticas por rol (ver abajo). Toda vista usa `security_invoker = true`, y el test de catálogo lo verifica.

**Roles.** Esta tabla es exhaustiva: un permiso que no aparece aquí no existe. El test de catálogo compara `table_privileges`, `column_privileges` y `routine_privileges` (incluido el grantee `PUBLIC`) con el archivo declarativo `db_grants.yaml`, que refleja esta tabla y que cada historia amplía con sus tablas.

| Rol | Uso | Permisos |
| --- | --- | --- |
| `concilia_owner` | Migraciones, `make create-org` y dueño de los objetos y de las funciones `SECURITY DEFINER` | Todo, con `BYPASSRLS` |
| `concilia_app` | API | Sin `BYPASSRLS`. SELECT e INSERT en todas las tablas de organización y en `jobs` (política: solo filas de `app.org_id`). UPDATE solo en `organizations(name, tolerance_min_cents, tolerance_bp, detraction_rates_bp)`, `memberships(removed_at)`, `invitations(revoked_at)`, `bank_accounts(bank, alias, number_last4, archived_at)`, `import_profiles(name, config, archived_at)`, `import_files(status, error_code, row_count, confirmed_at, discarded_at, voided_at, void_reason)`, `bank_movements(voided_at)`, `receivables(due_on, amount_cents, updated_at, cancelled_at, cancel_reason)`, `engine_runs(proposals_count, finished_at)`. DELETE solo en `member_roles` e `import_rows`. Sin RLS: SELECT, INSERT y UPDATE(`password_hash`, `display_name`) en `users`; todo en `sessions` y `rate_limits`. EXECUTE en `app_user_orgs`, `app_accept_invitation`, `app_ai_usage_today` y `app_refresh_stats` |
| `concilia_worker` | Worker | Los mismos permisos que `concilia_app` sobre tablas de organización. En `jobs`: SELECT, INSERT y UPDATE(`status`, `progress`, `attempts`, `run_after`, `locked_at`, `error_code`, `finished_at`) sobre todas las filas (política propia). SELECT(`id`, `display_name`) en `users`. EXECUTE en `app_cleanup`, `app_ai_usage_today` y `app_refresh_stats` |
| `concilia_backup` | `pg_dump` | `BYPASSRLS`, solo SELECT |

**Funciones `SECURITY DEFINER`** (dueño `concilia_owner`, `search_path` fijo, la hora siempre por parámetro). La migración ejecuta `REVOKE ALL ON FUNCTION … FROM PUBLIC` en cada una y `ALTER DEFAULT PRIVILEGES FOR ROLE concilia_owner REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC`; solo los roles de la tabla tienen EXECUTE.

| Función | Qué hace | La ejecuta |
| --- | --- | --- |
| `app_user_orgs(p_user_id)` | Organizaciones activas y roles de un usuario, para elegir organización al iniciar sesión | `concilia_app` |
| `app_accept_invitation(p_token_hash, p_user_id, p_now, p_event_id)` | En una transacción y bajo el bloqueo de la organización: valida que la invitación exista, no esté aceptada, revocada ni vencida, que su correo sea el del usuario y que el usuario no sea ya miembro activo; crea o reactiva la membresía con exactamente los roles de la invitación; marca `accepted_at`; registra `invitation.accepted` en `audit_events` con el id `p_event_id` que genera la aplicación. Devuelve la organización. Un usuario existente acepta después de iniciar sesión | `concilia_app` |
| `app_ai_usage_today(p_from, p_to)` | Cantidad de trabajos `ai_suggest` de organizaciones que no son de demo, de toda la instancia, creados en ese rango | `concilia_app`, `concilia_worker` |
| `app_refresh_stats()` | Ejecuta `ANALYZE` sobre `bank_movements`, `receivables`, `matches`, `match_items` y `match_decisions` para que el planificador conozca las filas recién cargadas. Se llama después de crear una demo y al confirmar una importación; sin ella, hasta que autovacuum analiza las tablas, el planificador estima una fila por organización y elige planes cuadráticos | `concilia_app`, `concilia_worker` |
| `app_cleanup(p_now)` | Borra exportaciones vencidas, descarta vistas previas de más de 24 horas (y sus filas) y llama a `app_reset_demo` para cada demo vencida | `concilia_worker` |
| `app_reset_demo(p_org_id)` | Toma el bloqueo de la organización y, si tiene `is_demo`, borra en orden de dependencias todos sus datos, sus trabajos, las sesiones de sus usuarios y sus usuarios de demo | Solo desde `app_cleanup` |

### Identidad y sistema

| Tabla | Columnas principales | Restricciones clave |
| --- | --- | --- |
| `users` | id, email, password\_hash, display\_name, is\_demo, created\_at | `email` único sin distinguir mayúsculas; Argon2id; los de demo tienen correo `demo+<id>@concilia.invalid` y no pueden iniciar sesión con contraseña |
| `sessions` | id, user\_id, organization\_id, token\_hash, created\_at, last\_seen\_at, expires\_at, revoked\_at | `token_hash` único; una organización activa por sesión |
| `rate_limits` | key\_hash, window\_start, count | PK `(key_hash, window_start)`; `UNLOGGED`; IP y correo como hash; se usa para inicio de sesión y creación de demos |
| `jobs` | id, organization\_id, kind, payload `jsonb`, status, progress, attempts, run\_after, locked\_at, dedup\_key, error\_code, created\_by, created\_at, finished\_at | RLS: `concilia_app` solo ve y crea filas de su organización; `concilia_worker` ve todas. kind ∈ noop, parse\_import, confirm\_import, run\_engine, ai\_suggest, export\_period, cleanup; status ∈ queued, running, done, failed; progress 0 a 100; organization\_id nulo solo en `cleanup` y `noop`; único `(kind, dedup_key)` donde status ∈ queued, running |

### Datos de cada organización (RLS)

| Tabla | Columnas principales | Restricciones clave |
| --- | --- | --- |
| `organizations` | id, name, tolerance\_min\_cents, tolerance\_bp, detraction\_rates\_bp `int[]`, is\_demo, demo\_expires\_at, created\_at | Política RLS sobre `id`; por defecto 100, 50 y {1000, 1200}; `demo_expires_at` obligatorio si y solo si `is_demo` |
| `memberships` | organization\_id, user\_id, created\_at, removed\_at | PK `(organization_id, user_id)`; una baja, bajo el bloqueo de la organización, pone `removed_at`, borra sus filas de `member_roles` y revoca sus sesiones en esa organización |
| `member_roles` | organization\_id, user\_id, role | PK `(organization_id, user_id, role)`; role ∈ admin, analyst, reviewer |
| `invitations` | id, organization\_id, email, roles `text[]`, token\_hash, created\_by, created\_at, expires\_at, accepted\_at, revoked\_at | `token_hash` único; un solo uso; vence a los 7 días |
| `bank_accounts` | id, organization\_id, bank, currency, alias, number\_last4, archived\_at | currency = PEN |
| `import_profiles` | id, organization\_id, kind, bank\_account\_id, name, config `jsonb`, archived\_at | kind ∈ bank\_statement, receivables; `bank_account_id` obligatorio si y solo si kind = bank\_statement; config validado con un modelo Pydantic versionado |
| `import_files` | id, organization\_id, kind, bank\_account\_id, import\_profile\_id, profile\_snapshot `jsonb`, filename, sha256, size\_bytes, content `bytea`, status, error\_code, row\_count, created\_by, created\_at, confirmed\_at, discarded\_at, voided\_at, void\_reason | status ∈ uploaded, parsing, previewed, failed, confirmed, discarded, voided; `bank_account_id` obligatorio si y solo si kind = bank\_statement; `import_profile_id` y `profile_snapshot` se escriben al subir; único `(bank_account_id, sha256)` donde status = confirmed |
| `import_rows` | id, organization\_id, import\_file\_id, row\_number, parsed `jsonb`, status, error\_code | status ∈ ok, error, duplicate, closed\_period, conflict; se borran al confirmar o descartar |
| `bank_movements` | id, organization\_id, bank\_account\_id, import\_file\_id, booked\_on, amount\_cents, description, description\_norm, operation\_number, fingerprint, doc\_refs `text[]`, created\_at, voided\_at | amount ≠ 0 (positivo = abono); único `(bank_account_id, fingerprint)` donde voided\_at es nulo |
| `receivables` | id, organization\_id, import\_file\_id, customer\_name, customer\_name\_norm, customer\_tax\_id, doc\_number, doc\_number\_norm, issued\_on, due\_on, amount\_cents, created\_at, updated\_at, cancelled\_at, cancel\_reason | amount > 0; único `(organization_id, doc_number_norm)` |
| `period_events` | id, seq, organization\_id, bank\_account\_id, period, action, reason, decided\_by, decided\_at | action ∈ close, reopen; trigger que exige alternar (no cerrar uno cerrado ni reabrir uno abierto); reason obligatorio al reabrir; solo inserción |
| `engine_runs` | id, organization\_id, bank\_account\_id, period, job\_id, rules\_version, proposals\_count, started\_at, finished\_at | `job_id` único; nulo solo en la precarga de la demo, garantizado por el dominio; se cierra al terminar |
| `matches` | id, organization\_id, bank\_account\_id, source, rule, score, suggested\_difference\_reason, explanation, engine\_run\_id, ai\_suggestion\_id, created\_by, created\_at | source ∈ engine, ai, manual; CHECK: `(source = 'engine') = (rule, score y engine_run_id no nulos y created_by nulo)`; CHECK: `(source = 'ai') = (ai_suggestion_id no nulo)`; score nulo fuera del motor; solo inserción |
| `match_items` | id, organization\_id, match\_id, bank\_movement\_id, receivable\_id, applied\_cents | Exactamente uno de bank\_movement\_id o receivable\_id; applied\_cents > 0 si y solo si es un cobro; únicos `(match_id, bank_movement_id)` y `(match_id, receivable_id)`; trigger: el movimiento es un abono no anulado de la cuenta de la coincidencia y no está en otra coincidencia activa, el cobro no está anulado, lo aplicado no supera su saldo disponible y la coincidencia aún no tiene decisiones; trigger diferido al confirmar la transacción: al menos un abono y un cobro; solo inserción |
| `match_decisions` | id, seq, organization\_id, match\_id, action, reason, difference\_reason, difference\_note, decided\_by, decided\_at | action ∈ confirm, discard, approve, reject, revert; único `(match_id, action)`; trigger que valida la transición de la tabla de estados, los cuatro ojos, que ningún abono esté en un período cerrado y, al confirmar, que haya motivo de diferencia si y solo si la diferencia no es 0 (`overpayment` solo si es positiva); solo inserción |
| `ai_suggestions` | id, organization\_id, job\_id, bank\_movement\_id, model, prompt\_version, candidates `jsonb` (alias → id), response `jsonb`, server\_applied `jsonb`, valid, replayed, input\_tokens, output\_tokens, created\_by, created\_at | `job_id` único; solo se escribe cuando la llamada al proveedor respondió (válida o no); un intento fallido no escribe aquí y su error queda en `jobs.error_code`; solo inserción |
| `ai_suggestion_decisions` | id, seq, organization\_id, ai\_suggestion\_id, suggestion\_index, action, reason, match\_id, decided\_by, decided\_at | action ∈ accept, reject; único `(ai_suggestion_id, suggestion_index)`; match\_id obligatorio si y solo si acepta; solo inserción |
| `exports` | id, organization\_id, bank\_account\_id, period, job\_id, content `bytea`, created\_by, created\_at, expires\_at | `job_id` único; las borra `app_cleanup` a las 24 horas |
| `audit_events` | id, seq, organization\_id, actor\_user\_id, action, entity, entity\_id, metadata `jsonb`, at | Solo inserción; `action` de la lista cerrada de `audit.domain` (por ejemplo `import.confirmed`, `match.approved`, `period.closed`, `ai_suggestion.accepted`); `entity` de la lista cerrada de `audit.domain`; metadata sin datos de clientes (claves permitidas en una lista, también como CHECK `audit_events_metadata_keys` en la base) |

**Estados calculados.** El estado de una coincidencia (`match_status`), los saldos abierto y disponible de un cobro (`receivable_balances`) y el estado de un período (`period_status`) se calculan al leer con vistas `security_invoker`, con índices sobre `(match_id, seq)`, `(receivable_id)` en `match_items` y `(bank_account_id, period, seq)` en `period_events`.

## Plan de sprints

Diez sprints de una semana (de lunes a domingo, salvo S2), planificados a unos 10 puntos con Claude Code implementando y revisión de cada PR, con menos carga en las semanas de Navidad y Año Nuevo y una pausa del 6 al 20 de diciembre. El primer hito es una **demo mínima funcionando en local el viernes 15 de enero de 2027**; la publicación llega con CN-04, al final del plan, y el proyecto completo queda listo el 7 de febrero.

| Sprint | Fechas | Objetivo | Historias, en orden | Pts |
| --- | --- | --- | --- | --- |
| S0 | 16 – 22 nov 2026 | Decisiones, monorepo con CI y base segura | CN-01, 02, 03 | 10 |
| S1 | 23 – 29 nov | Inicio de sesión y el motor de conciliación | CN-05, 11 | 8 |
| S2 | 30 nov – 5 dic (6 días) | Aplicación Angular base, equipo y configuración | CN-06, 07, 08 | 10 |
| Pausa | 6 – 20 dic | — | — | — |
| S3 | 21 – 27 dic | Importación de extractos | CN-09 | 5 |
| S4 | 28 dic – 3 ene 2027 | Importación de cobros y motor en la base | CN-10, 12 | 6 |
| S5 | 4 – 10 ene | Bandeja de revisión y demo por visitante | CN-13, 22 | 8 |
| S6 | 11 – 17 ene | Cuatro ojos | CN-14 | 5 |
| Hito | vie 15 ene | **Demo mínima en local:** entrar a la demo, importar el tercer mes, correr el motor, confirmar y aprobar con dos roles, con `docker compose up` | — | — |
| S7 | 18 – 24 ene | Manual y en lote, cierre de mes y auditoría | CN-15, 16, 19 | 9 |
| S8 | 25 – 31 ene | Panel, Excel y motor de IA | CN-17, 18, 20 | 10 |
| S9 | 1 – 7 feb | IA en la interfaz, recorrido guiado y cierre de portafolio | CN-21, 23, 24 | 9 |
| Final | después de S9 | Publicación: servidor con dominio, HTTPS y despliegue automático | CN-04 | 2 |

**Puertas de decisión**

- **Fin de S0 (22 nov):** si CN-03 no está en verde, se termina antes de tocar la interfaz y todo el plan se corre una semana (S2 pasaría a después de la pausa y el hito al 22 de enero).
- **Fin de S2 (5 dic):** si queda alguna historia de S0 a S2 sin terminar, se protege el hito liberando capacidad antes del 15 de enero, en este orden y solo lo necesario:
  1. CN-07 (equipo e invitaciones) pasa a S7, antes de CN-19; la demo no la necesita.
  2. La configuración de tolerancias y detracciones de CN-08 pasa a S7 (se usan los valores por defecto).
  3. La prueba de p95 de CN-13 pasa a S7.
  4. CN-22 entra sin los archivos descargables, y el hito pasa a "conciliar y aprobar sobre los datos precargados".
  Ninguna medida toca el motor, los cuatro ojos ni el aislamiento entre organizaciones.
- **Fin de S6 (17 ene):** si la velocidad sigue baja, se recorta después del hito en este orden: CN-19 (y CN-24 deja de depender de ella), CN-23 se reduce a un texto de ayuda en la entrada de la demo, y CN-17 se reduce a tres números sin gráficos. Nunca se recortan el motor, los cuatro ojos, el aislamiento entre organizaciones ni la IA controlada.

## Requisitos no funcionales y seguridad

| Categoría | Requisito | Cómo se verifica |
| --- | --- | --- |
| Corrección | El motor es determinista, nunca usa un abono dos veces ni excede el saldo disponible de un cobro; los saldos abierto y disponible siempre cumplen sus definiciones | Propiedades con Hypothesis y casos de ejemplo por regla |
| Cuatro ojos | Nadie aprueba ni rechaza lo que creó o confirmó | Test en el dominio y test directo del trigger en SQL |
| Aislamiento | Ningún dato cruza organizaciones por la API, por SQL directo ni por vistas; ninguna tabla nueva queda sin RLS; ningún rol tiene permisos fuera de la tabla de roles | Tests con dos organizaciones por endpoint y test del catálogo |
| Concurrencia | Dos operaciones simultáneas nunca dejan un saldo disponible negativo ni dos decisiones incompatibles | Tests concurrentes en CN-07, CN-12, CN-14 y CN-15 |
| Idempotencia | Reenviar un POST o reejecutar un trabajo no duplica nada | Tests de reenvío y de reejecución |
| Cola | Un trabajo que falla llega a `failed` tras 3 intentos; uno colgado vuelve a la cola | Tests de integración en CN-03 |
| IA | Salida validada; aritmética recalculada; nada decide sola; funciona con la IA apagada; límites por organización y global | Tests con `FakeLlmClient`, incluidas respuestas inválidas y alias inventados |
| Importación | Sin evaluación de fórmulas ni entidades XML, límites de tamaño y filas, archivos repetidos rechazados | Tests con archivos maliciosos, enormes y repetidos |
| Exportación | Sin inyección de fórmulas en Excel | Test con valores que empiezan con `=`, `+`, `-`, `@`, tabulador y retorno de carro |
| Autenticación | Argon2id, sesiones revocables y rotadas, CSRF, límite de intentos | Tests de sesión, CSRF y 429 |
| Seguridad web | CSP de SPEC, HSTS, cookies `__Host-`, `Referrer-Policy: no-referrer`, escaneo de dependencias en CI | Test de cabeceras contra la app real |
| Logs | Sin datos de clientes ni de la IA | Test del procesador de structlog |
| Rendimiento | Motor sobre 1 000 abonos y 1 000 cobros en menos de 5 s; bandeja en menos de 500 ms (p95) con 10 000 movimientos | Benchmark en CI (CN-11) y prueba de carga simple (CN-13) |
| Accesibilidad | WCAG 2.1 AA; todo usable con teclado | axe en Playwright desde CN-06 |
| Tiempo | `Clock` inyectado; fines de mes y año bisiesto probados | Tests con reloj falso |
| Costo | Infraestructura bajo US$ 10 al mes; tope de gasto de IA en el proveedor y límite global diario | Revisión mensual |

**Privacidad.** Los datos de la demo son ficticios y lo dice la interfaz. En una organización real, a la IA solo se envían los campos definidos en las reglas, y el proveedor elegido no debe usarlos para entrenar (ADR-0006). Los prompts y las respuestas no van a los logs; quedan solo en `ai_suggestions`, dentro de la organización.

**Límites declarados** (van en el README y en la demo):

- Concilia no se conecta a bancos ni a sistemas contables.
- Las plantillas de bancos incluidas son ejemplos y deben verificarse con un extracto real.
- La IA puede equivocarse; por eso nunca decide sola.
- Un cobro pagado en partes en meses distintos se concilia a mano.

## Repositorio y convenciones

Un monorepo público en GitHub.

```text
concilia/
├── backend/
│   ├── src/concilia/
│   │   ├── shared/kernel/       # Clock, Money, ids, errores, normalización (puro)
│   │   ├── shared/infrastructure/
│   │   ├── audit/               # cada módulo: domain, application, infrastructure, api
│   │   ├── identity/
│   │   ├── banking/
│   │   ├── periods/
│   │   ├── imports/
│   │   ├── matching/
│   │   ├── ai/                  # prompts/ versionados, respuestas grabadas de la demo
│   │   ├── reporting/
│   │   ├── demo/
│   │   ├── api.py               # app FastAPI y cableado
│   │   └── worker.py            # cola, planificador y cableado
│   ├── migrations/
│   ├── tests/{unit,integration,architecture,benchmarks}/
│   └── pyproject.toml
├── web/
│   ├── src/app/core/            # interceptores, guards, layout
│   ├── src/app/features/        # auth, admin, imports, matching, ai, periods, reports, audit, demo
│   ├── src/app/api/             # generado con ng-openapi-gen (no se edita)
│   └── e2e/                     # Playwright + axe
├── infra/
│   ├── postgres/init/           # roles
│   ├── caddy/Caddyfile
│   └── deploy/
├── docs/
│   ├── SPEC.md                  # en español
│   ├── BACKLOG.md               # en español
│   ├── ARCHITECTURE_RULES.md    # en inglés
│   └── adr/                     # en inglés
├── docker-compose.yml
├── Makefile                     # up, down, test, lint, migrate, openapi, create-org, demo, record-ai
├── CLAUDE.md
└── README.md                    # en inglés
```

**Convenciones.** Ramas `feat/CN-NN-descripcion`; Conventional Commits; una historia puede tener varios PR, cada uno con la checklist de la definición de hecho; tablas y columnas en `snake_case`.
