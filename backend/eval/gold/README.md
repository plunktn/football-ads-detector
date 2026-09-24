# Minutos gold

Clips etiquetados a mano para comparar la duración LED de las marcas de
interés con el detector, sin volver a auditar el partido completo. No subas
el video: `*.mp4` está en `.gitignore` y esta carpeta solo guarda JSON.

El pass mira **solo tramos medibles** (no dudosos) y tiene que caer en
**±15–20%**. `doubtful_segments` del `result.json` se restan de los dos
lados antes del error. Un tramo sin `doubtful` sigue contando como tiempo
limpio.

## Qué va en el JSON

| Campo | Uso |
| --- | --- |
| `labels` | Tramos que viste. `start_s` / `end_s` son segundos del archivo (el reloj del reproductor), no el índice de frame. |
| `doubtful` / `measurable` | `doubtful: true` o `measurable: false` = ilegible o que no se audita. No entra al error. |
| `quality` | `good`, `ok` o `bad`. Es una nota; no cambia el cálculo. |
| `interest_brands` | Ids canónicos (`backend/config/interest_brands.yaml`). Solo esas marcas deciden el PASS/FAIL. El resto sale como `fuera`. |
| `expected_seconds` | Segundos medibles que esperas por marca de interés. Tiene que coincidir con la suma de sus `labels` no dudosas. Si no cuadra, el reporte es FAIL antes de mirar al detector. |
| `clock_mode`, `second_half_start_sec` | Contexto del clip. En un reloj continuo el 2T no vuelve a 00:00. Libertad vs Orense: inicio de 2T ≈ 4145 s de archivo. Eso no es una duración de marca. |
| `video` | Déjalo en `null`. |
| `synthetic` | `true` si los segundos están inventados para probar el harness. |

No solapes dos filas medibles de la misma marca: el harness suma duraciones.

`clips/example.json` es solo el formato mínimo. Sin `--detector` el error sale
`n/a`. Eso no es una medición.

`clips/synthetic_interest.json` es un partido **inventado** con las marcas de
interés, tramos medibles, un tramo dudoso y segundos esperados. El detector
pareja está en `fixtures/synthetic_interest_detector.json`. No cites esos
números como si fueran Libertad vs Orense.

## Etiquetar un clip real

1. Elige una ventana que puedas mirar entera (un bloque de minutos, no el
   partido completo la primera vez).
2. Anota el segundo de archivo en el que la LED muestra la marca y el segundo
   en el que cambia. Usa el tiempo del reproductor.
3. Una fila por tramo continuo y por marca. `brand_id` igual al id del
   catálogo de interés (`ecuabet`, `nettplus`, `lions`, `1xbet`, `siete-com`,
   `grand-aviation`).
4. Si la valla está en cuadro pero no puedes leerla, marca
   `doubtful: true` y `measurable: false`. Esos segundos no entran al ±15–20%.
5. Si la cámara no muestra la valla (close-up, bumper, plano abierto), no lo
   etiquetes como dudoso: la LED no estaba.
6. Suma los tramos medibles de cada marca de interés y escríbelo en
   `expected_seconds`. El script falla si esa suma no coincide con las filas.
7. Copia el archivo a `clips/<id>.json`. No pongas `synthetic: true` en un
   clip real, y no reutilices los segundos del fixture.

## Comparar

```bash
cd backend
python eval/gold/compare_gold.py --gold eval/gold/clips/synthetic_interest.json
python eval/gold/compare_gold.py \
  --gold eval/gold/clips/synthetic_interest.json \
  --detector eval/gold/fixtures/synthetic_interest_detector.json \
  --tolerance 15
python eval/gold/compare_gold.py \
  --gold eval/gold/clips/<id>.json \
  --detector data/jobs/<job>/result.json \
  --tolerance 20
```

`--tolerance` es el error absoluto máximo. `20` es el extremo ancho de la
banda comercial; `15` es el estricto. Otro valor se avisa en el reporte y no
sustituye la banda.

`--detector` acepta una lista de segmentos o el `result.json` del job. De ese
archivo se leen las marcas LED (`brands`) y `doubtful_segments`. Las vallas
fijas (`fixed_brands`) no entran.

Salida `0` = PASS (o aún no hay detector). Salida `1` = FAIL. Salida `2` =
JSON ilegible.

## Cómo se lee el pass

- `PASS` / `FAIL` por marca: error de duración contra el gold medible.
- `fuera`: la marca no está en `interest_brands`. Se imprime y no tumba el pass.
- `n/a`: falta el detector, o no hay segundos medibles para comparar.
- Línea `tiempo dudoso (etiquetas, excluido del pass)`: lo que marcaste
  ilegible.
- Línea `tiempo no medible (detector, excluido)`: `doubtful_segments` del
  job, restados de los dos lados.
- `pass (±15% en tramos no dudosos): PASS` es el resultado que se puede citar.
