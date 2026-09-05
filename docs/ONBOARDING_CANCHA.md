# Checklist: onboarding de cancha nueva

Usar al agregar un estadio al sistema (Fase 5).

## 1. Datos mínimos

- [ ] Id estable (`slug`): solo `a-z0-9_` (ej. `capwell`)
- [ ] Nombre visible y país
- [ ] Variante de cámara: `default` / `dia` / `noche`

## 2. Perfil YAML

- [ ] Copiar `backend/config/stadiums/ligaecuabet.yaml` → `backend/config/stadiums/<id>.yaml`
- [ ] Ajustar `scoreboard_crop`, `grass_hsv`, `led_band`, `matte_yellow` (o quitar matte si no aplica)
- [ ] Definir `panel_zones` (al menos `LATERAL_MAIN` / `LED_DYNAMIC`)
- [ ] `PYTHONPATH=backend python -c "from app.config.stadiums import load_stadium_profile; print(load_stadium_profile('<id>'))"`

## 3. Ground truth

- [ ] Crear `data/eval/<id>/` con `brands.json` + `annotations.json` (formato plano)
- [ ] Agregar clip MP4 2–5 min (no commitear el video)
- [ ] Correr:

```bash
python backend/scripts/eval_pipeline.py --dataset data/eval/<id>
```

- [ ] Guardar `baseline.json` y revisarlo

## 4. Validación operativa

- [ ] UI: el estadio aparece en el selector
- [ ] Job de prueba E2E con ese `stadium_id`
- [ ] Comparar vs baseline: `python backend/scripts/check_drift.py --dataset data/eval/<id> --threshold 0.05`

## 5. Deriva

- [ ] Si precision/recall cae >5 pp, reabrir wizard de calibración (solo el paso conflictivo)
- [ ] Versionar perfil (nueva versión en `camera_profiles` / YAML) sin borrar la anterior
