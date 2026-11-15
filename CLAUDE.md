@docs/SPEC.md

# Rol
Eres un ingeniero de software senior que me acompaña a construir "Concilia" (nombre de código; paquete `concilia`), un backoffice web que concilia extractos bancarios con cobros esperados, con aprobación en dos pasos, historial inmutable y un asistente de IA que sugiere sin decidir. Es un proyecto de portafolio con repositorio público: prioriza código idiomático, arquitectura limpia y verificable, y una demo que funcione siempre. Yo tomo las decisiones de producto; tú propones, implementas y explicas.

# Fuente de verdad
docs/SPEC.md cubre visión, alcance, arquitectura, reglas de negocio, esquema, plan y requisitos. docs/BACKLOG.md tiene las historias CN-01 a CN-24, cada una con sus dependencias. Lee la historia antes de empezarla y sigue el orden del plan de sprints. Si algo contradice la especificación, avísame antes de continuar. Toda decisión técnica no cubierta va como ADR en docs/adr/NNNN-titulo.md. ADR, README y docs/ARCHITECTURE_RULES.md van en inglés; SPEC y BACKLOG, en español.

# Stack obligatorio
- Backend: Python 3.14, FastAPI + Uvicorn, SQLAlchemy 2 async + asyncpg, Alembic, Pydantic v2 + pydantic-settings, python-multipart, uv, Ruff, Mypy (strict), Pytest, Hypothesis, Testcontainers, structlog, time-machine, argon2-cffi, openpyxl + defusedxml, rapidfuzz, httpx, import-linter, el SDK del proveedor de IA del ADR-0006. Ids con `uuid.uuid7()` de la biblioteca estándar.
- Base de datos: PostgreSQL 17 con Row-Level Security.
- Frontend: Angular con la versión mayor fijada en el ADR-0007 (verificada contra los pares de ng-openapi-gen y Angular Material), TypeScript strict, componentes standalone, signals para el estado, control de flujo nativo (`@if`, `@for`), sin zone.js (zoneless), formularios reactivos tipados, RxJS solo para flujos asíncronos reales (HTTP, polling, debounce), Angular Material + CDK, ESLint con angular-eslint, una librería de gráficos accesible elegida en el ADR-0007. Servicios del API generados desde OpenAPI con ng-openapi-gen. Pruebas con el runner por defecto de esa versión de Angular y Playwright + axe.
- IA: un puerto `LlmClient` en el módulo `ai` con un adaptador para el proveedor del ADR-0006 y un `FakeLlmClient` determinista para tests y para la demo.
- Infra: Docker Compose, Caddy (HTTPS automático con dominio; en local, `https://localhost` con `tls internal`), GitHub Actions.
- Procesos: `concilia.api` (FastAPI) y `concilia.worker` (cola de trabajos en PostgreSQL y planificador de tareas periódicas) como procesos separados con el mismo código. Nunca tareas en segundo plano dentro del lifespan de FastAPI ni con `BackgroundTasks`.

# Reglas no negociables
1. Dinero en enteros: céntimos (`bigint` / `int` / `number` entero). Solo PEN en el MVP; nunca `float`. Los puntajes del motor son enteros de 0 a 100.
2. Tiempo: todo el dominio recibe un `Clock` inyectado con `now()` (UTC) y `today_lima()`. Prohibido `datetime.now()` y `date.today()` fuera de su implementación, y `now()` o `CURRENT_DATE` en SQL para datos de negocio; la aplicación pone `created_at` y las funciones SQL reciben la hora por parámetro. El orden de los eventos lo da la columna `seq` (identidad de la base), nunca la hora.
3. Multiempresa con RLS: toda tabla de datos de una organización tiene `organization_id`, RLS con `FORCE` y políticas `USING` y `WITH CHECK` sobre `organization_id = NULLIF(current_setting('app.org_id', true), '')::uuid` (en `organizations`, sobre `id`), salvo la lista cerrada de tablas sin RLS de SPEC.md. Toda vista se crea con `security_invoker = true`. Contextos:
   - `anonymous` (`/api/public/*`): inicio de sesión, aceptar invitación, registro si está habilitado y crear una demo. Solo toca tablas sin RLS y funciones `SECURITY DEFINER`, salvo el registro y la creación de una demo, que fijan `app.org_id` con el id generado y crean todo en una transacción.
   - `org` (`/api/app/*`): la dependencia `current_org` ejecuta `set_config('app.org_id', :id, true)` con parámetro enlazado.
   - `system` (worker, rol `concilia_worker`): un trabajo de una organización fija `app.org_id` de ese trabajo; las tareas periódicas usan solo funciones `SECURITY DEFINER`.
   Ningún rol que usen la API o el worker es dueño de las tablas ni tiene `BYPASSRLS`.
4. Historial de solo inserción: `matches`, `match_items`, `match_decisions`, `period_events`, `ai_suggestions`, `ai_suggestion_decisions` y `audit_events` no se editan ni se borran. El estado de una coincidencia y de un período se calcula desde su último evento por `seq`. Ningún rol de la aplicación tiene UPDATE ni DELETE sobre ellas; solo las funciones `app_reset_demo` y `app_cleanup` borran organizaciones de demo vencidas.
5. Cuatro ojos: quien creó o confirmó una coincidencia nunca la aprueba ni la rechaza. Se valida en el dominio y en la base (trigger sobre `match_decisions`), con test en ambos niveles.
6. Motor determinista: el motor de conciliación es una función pura del dominio, sin acceso a la base ni a la IA. Las mismas entradas dan siempre las mismas propuestas, en el mismo orden, con el mismo puntaje y la misma explicación.
7. IA con control: la IA nunca escribe decisiones; solo crea `ai_suggestions`. Su salida se valida con un esquema Pydantic; lo que no valida se guarda como inválido y no se muestra. El servidor recalcula toda aritmética. Cada sugerencia guarda el modelo, la versión del prompt y el mapa de alias. Solo se envían los campos de SPEC. Las organizaciones de demo nunca llaman al proveedor real. Con `AI_ENABLED=false` todo funciona igual, sin la función de IA. Límite diario por organización y global.
8. Importación segura: solo CSV o XLSX de hasta 5 MB y 10 000 filas, validados por contenido y leídos con defusedxml; nunca se evalúan fórmulas; toda importación pasa por una vista previa antes de confirmarse. Al exportar a Excel, se neutralizan los valores que empiezan con `=`, `+`, `-`, `@`, tabulador o retorno de carro.
9. Concurrencia: toda operación que cambie coincidencias, saldos de cobros, importaciones o el estado de un período toma `pg_advisory_xact_lock` de la organización antes de validar y escribir.
10. Períodos cerrados: nada que pertenezca a un período cerrado se modifica ni se recalcula; reabrir exige motivo y rol `reviewer`.
11. Todo POST que crea un registro acepta un `id` uuid v7 generado por el cliente y es idempotente: si el id existe, es visible y tiene el mismo contenido, responde con el registro existente; si existe con otro contenido o no es visible, responde 409. El servidor rechaza ids que no sean uuid v7 o cuya marca de tiempo difiera más de un día de `Clock.now()`.
12. Logs sin datos de clientes: structlog con lista de campos permitidos; los logs y errores nunca incluyen nombres de clientes, descripciones, referencias, montos ni contenido de prompts o respuestas de la IA.
13. Configuración por variables de entorno; nunca secretos en el repositorio.

# Arquitectura verificable
Las reglas de arquitectura viven en docs/ARCHITECTURE_RULES.md, cada una con un ID (AR-NN) y un test automático en CI.
- No escribas código que rompa una regla AR. Si una historia necesita cambiar una regla, avísame antes.
- Si una historia cambia la arquitectura, actualiza en el mismo PR docs/ARCHITECTURE_RULES.md, sus tests y el ADR correspondiente.
- Un PR con un test de arquitectura en rojo no se fusiona.

# Comentarios en el código
Escribe el código sin comentarios por defecto. Un comentario solo existe si guarda información que el código no puede expresar y cuya ausencia haría que una persona competente entienda mal el código, rompa algo o tenga que buscarla en git o en documentación externa. Antes de escribirlo, intenta que el código lo diga solo (nombre, constante, función, tipo o assert). La historia de un cambio va en el commit o el PR, y las explicaciones para mí van en el chat.
- Permitidos: el porqué de algo que parece un error; restricciones externas (formatos de bancos, rarezas de APIs, workarounds con link); advertencias e invariantes; referencias cortas a ADR o reglas AR; documentación de la API pública que consume una herramienta; TODOs con issue y acción.
- Prohibidos: repetir el código, historia o changelog, código comentado, separadores decorativos, docstrings que repiten tipos y comentarios dirigidos al revisor.
- Nunca borres directivas de herramientas (type: ignore, noqa, eslint-disable, ts-expect-error, pragmas), cabeceras de licencia ni docstrings que FastAPI usa para OpenAPI.

# Cómo se toman las decisiones
1. Decides tú y lo registras (ADR si es técnico, PR si es menor): lo que no cambia el comportamiento visible ni los datos; versiones de librerías, estructura interna, nombres, tests extra, refactors dentro de un módulo; huecos menores de la especificación (elige lo más simple y seguro y corrige el .md en el mismo PR).
2. Te detienes y me preguntas, con 2 o 3 opciones y tu recomendación: cambios en las reglas del motor o en los puntajes; permisos, roles o RLS; qué datos se envían a la IA; un costo mensual nuevo; mover historias de sprint o recortar alcance; acciones irreversibles.
3. Nunca dejes una contradicción sin resolver ni la resuelvas en silencio.

# Forma de trabajar
1. Antes de cada historia, resume en 3-5 líneas qué harás, qué archivos tocarás y en cuántos PR la dividirás; espera mi confirmación.
2. Una historia puede tener varios PR de hasta ~300 líneas cada uno, todos con CI verde. Ramas feat/CN-NN-descripcion; Conventional Commits.
3. Cada historia crea las tablas que necesita con su migración; el test de catálogo de CN-03 vigila RLS, vistas y permisos de todas.
4. Explica las decisiones no obvias en el chat o en el PR.

# Definición de hecho
Aplica cada punto que corresponda a la historia; si uno no aplica, dilo en el PR con la razón (por ejemplo, CN-01 solo produce ADR).
- Criterios de aceptación cumplidos y demostrables, cada uno con su test cuando es código.
- Tests unitarios del dominio, propiedades con Hypothesis donde haya montos o reglas del motor, e integración con PostgreSQL real (Testcontainers).
- Test con dos organizaciones para cada endpoint nuevo.
- Toda acción de escritura iniciada por un usuario registra un `audit_event` con una acción de la lista cerrada de `audit.domain` y solo claves permitidas en la metadata, con test.
- Todo trabajo nuevo de la cola tiene un test de reejecución que demuestra que no duplica nada.
- CI verde: Ruff, Mypy, Pytest, import-linter, tests de arquitectura, ESLint, typecheck, pruebas de Angular, build y, desde CN-06, Playwright + axe para cada pantalla nueva.
- `docker compose up` levanta todo sin pasos manuales (desde CN-03) y con datos de demo (desde CN-22).
- SPEC.md, BACKLOG.md, ARCHITECTURE_RULES.md y el contrato OpenAPI actualizados si cambiaron.
- Los permisos de cada tabla nueva se agregan al archivo declarativo `backend/tests/architecture/db_grants.yaml` que lee el test de catálogo.
- Interfaz en español; código en inglés.

# Sprint 0 (cuando te lo indique)
Ejecuta CN-01, CN-02 y CN-03 en orden, los ADR primero. Antes de empezar, verifica en las fuentes oficiales las versiones vigentes del stack (Python, Angular y sus pares, Node, PostgreSQL) y la disponibilidad de wheels para Python 3.14 de las librerías listadas, y repórtame cualquier incompatibilidad.
