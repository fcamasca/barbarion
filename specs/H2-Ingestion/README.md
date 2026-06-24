# H2 — Ingestion

**Estado:** pendiente; depende de H1.

Transformar un corpus autorizado del sistema legacy objetivo en fragmentos trazables, metadata consultable e índice incremental.

El alcance y los criterios iniciales están en [ROADMAP.md](../../docs/ROADMAP.md#4-h2--ingestion).

## Consideración trasladada desde H1

La spec de H2 debe incluir la activación y verificación de `PRAGMA journal_mode = WAL` antes de escribir metadata de ingesta. H1 conserva el modo de journal predeterminado de SQLite y no modifica esta configuración.
