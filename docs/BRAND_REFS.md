# Referencias de marca (creativos LED)

## Objetivo

Medir **tiempo en pantalla** de una marca cuando el LED muestra su creativo:
imagen fija **o** video/animación (a veces eslogan sin el nombre de marca).

## Fase 1 (hecha)

- Cada marca puede guardar **varias referencias visuales**: logo, fotos y
  frames extraídos de un **video de pauta**.
- El video se muestrea ~1 fps, se deduplica (pHash) y se guardan hasta ~32
  keyframes. El MP4 no se conserva.
- API: `GET/POST/DELETE /brands/{id}/refs` (+ `.../image`).
- UI: Configuración → referencias por marca.

## Fase 2 (pendiente) — matching para dwell time

Usar **todas** las refs (no solo el logo) al analizar el partido:

1. **OCR + aliases** — eslóganes / variantes de texto (“Somos tu mejor opción”
   → NETT plus) aunque el nombre no aparezca.
2. **Template / visual match** contra N refs (logo + fotos + keyframes) por
   cada muestra de LED.
3. **CLIP / embeddings** solo si OCR + template no bastan.

Resultado esperado: segundos acumulados por marca mientras el creativo está
en la valla, estéticos o en movimiento.

No implementar fase 2 en este slice.
