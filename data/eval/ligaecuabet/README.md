# Dataset de evaluación — LigaEcuabet

Ground truth para la cancha de referencia. Sirve para medir precisión/recall
antes de generalizar a otras canchas (Fase 0 del plan multi-cancha).

## Estructura

```
data/eval/ligaecuabet/
├── README.md
├── brands.json         # marcas a detectar
├── annotations.json    # lista plana de intervalos GT
├── baseline.json       # generado por eval (reproducible)
└── *.mp4               # clips (operador; gitignored)
```

## Agregar clips

1. Copia MP4 cortos (2–5 min) en este directorio.
2. Edita `annotations.json` (lista plana):

```json
{
  "clip": "mi_clip.mp4",
  "marca": "NETT plus",
  "brand_id": "nettplus",
  "zone": null,
  "start_s": 205.0,
  "end_s": 221.0
}
```

`sample_clip.mp4` es placeholder: puede no existir. Sin clips, el script escribe
baseline con predicciones en cero (útil para verificar reproducibilidad).

## Correr eval

Desde la raíz del repo:

```bash
python backend/scripts/eval_pipeline.py --dataset data/eval/ligaecuabet
# o forzar predicciones vacías:
python backend/scripts/eval_pipeline.py --dataset data/eval/ligaecuabet --synthetic
```

Imprime `marca | precision | recall | error_s` y escribe `baseline.json`.
Dos corridas idénticas deben producir el mismo archivo.

## Caso canónico

| Reloj 1T | Marca en LED         | No contar                |
| -------- | -------------------- | ------------------------ |
| ~03:25   | NETT plus            | Lona fija NETTPLUS arriba |
| ~03:27   | Lions Sports & Media | NETT solo en lona fija   |
