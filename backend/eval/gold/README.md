# Minutos gold (esqueleto)

Clips etiquetados a mano para comparar duración LED por marca, sin volver a
auditar el partido completo. No subas el video: `*.mp4` está en `.gitignore`
y este folder solo guarda JSON.

## Agregar un clip

1. Copia `clips/example.json` a `clips/<id>.json`.
2. Completa `labels`. Cada fila es un tramo continuo de una marca:
   - `brand` y, si existe, `brand_id` (el mismo id del catálogo).
   - `start_s`, `end_s`: segundos de video. La duración es `end_s - start_s`.
   - `quality`: `good`, `ok` o `bad` (anotación; no entra al cálculo).
   - `doubtful`: `true` si el tramo es ilegible o no se debe auditar.
   - `half`: `1T` o `2T`, opcional.
3. No solapes dos filas de la misma marca: el harness suma duraciones.
4. Deja `video` en `null`.

## Comparar

```bash
cd backend
python eval/gold/compare_gold.py --gold eval/gold/clips/<id>.json
python eval/gold/compare_gold.py \
  --gold eval/gold/clips/<id>.json \
  --detector data/jobs/<job>/result.json \
  --tolerance 20
```

`--detector` acepta una lista de segmentos (`brand` / `brand_id`, `start_s`,
`end_s`) o el `result.json` de un job. De ese archivo solo se leen las marcas
LED (`brands`), no `fixed_brands`.

## Qué es pass

En tramos con `doubtful: false`, el error de duración por marca debe quedar
dentro de **±15–20%** frente al ojo humano. El default del script es 20
(`--tolerance 15` para el extremo estricto).

El % dudoso es el tiempo etiquetado con `doubtful: true` sobre el tiempo
etiquetado total. Esos segundos no entran al error. El detector todavía no
marca dudosos: si el segmento no trae `doubtful`, cuenta como tiempo limpio.

`clips/example.json` es solo formato. Corrido sin `--detector` imprime el
% dudoso de esas filas de ejemplo y deja el error en `n/a`. Eso no es un
resultado del detector.
