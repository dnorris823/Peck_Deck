# Models & Taxonomy

Weights are **fetched, not committed** — they are third-party binaries with
their own licences. `machine_learning/*.tflite` and `*.pth` are gitignored.

```bash
python scripts/fetch_models.py     # Tier 1 weights (~3.5 MB), digest-checked
python scripts/build_taxonomy.py   # regenerate taxonomy.csv from the label map
python scripts/validate_tier1.py   # measure real accuracy on known bird photos
```

## The two CSVs are not interchangeable

| File | Rows | What it is |
|---|---|---|
| `taxonomy.csv` | 965 | **The model's label space.** Row *N* is output index *N*. Generated — never hand-edit. |
| `feeder_species.csv` | 20 | A curated North American backyard list, a subset of the above. Hand-maintained. |

`taxonomy.csv` is a contract, not a list of interesting birds:
`tier1_tflite.py` does `self._taxa[argmax]`, so a row inserted in the wrong
place mislabels every sighting while still looking entirely plausible. Regenerate
it with `build_taxonomy.py` whenever the model changes, and re-run
`validate_tier1.py` — a misaligned taxonomy scores near zero there, which is the
only cheap way to catch it.

`feeder_species.csv` exists because the simulator and demo draw from it. Drawing
from all 964 would put limpkins and cranes on the dashboard, and
`species_weights()` would hand "most common feeder bird" to whatever happens to
sit at index 0 of the model's label map.

## Tier 1 — on-device (Pi)

**Google AIY `birds_V1`** — MobileNetV2 trained on iNaturalist bird imagery.

| | |
|---|---|
| Source | Kaggle Models — `google/aiy/tfLite/vision-classifier-birds-v1/2` |
| Label map | `https://www.gstatic.com/aihub/tfhub/labelmaps/aiy_birds_V1_labelmap.csv` |
| Classes | 964 species + a `background` class (index 964) |
| Input / output | `[1,224,224,3]` uint8 → `[1,965]` uint8, quant scale `1/256` |
| Measured | **20/20 top-1**, 57.9 ms/inference on a Pi 5, 12 ms load |

The uint8 output *must* be dequantised — `tier1_tflite.py` applies the output
tensor's scale/zero-point. Without it `confidence` is a 0–255 integer and the
0.5 threshold is meaningless.

## Tier 2 — LAN GPU server (RTX 5080)

**`hf-hub:timm/vit_large_patch14_clip_336.laion2b_ft_augreg_inat21`** — ViT-L/14
fine-tuned on iNaturalist 2021, 10,000 species.

| | |
|---|---|
| Classes | 10,000 (all of iNat21 — plants and insects included) |
| Mapped onto `taxonomy.csv` | **869 of 965** |
| Measured | **20/20 top-1**, 29.1 ms/inference, ~26 s cold load |

The two tiers share a label space by *projection*, not by architecture. The
checkpoint publishes `label_names` in its Hub `config.json`, so each output
index has a scientific name; `_build_projection` matches those against
`taxonomy.csv` and returns the taxonomy entry. This is what makes a Tier 1 and a
Tier 2 answer directly comparable.

**Softmax runs over all 10,000 classes, then the best *mapped* class is taken.**
Restricting before the softmax would renormalise a squirrel into a confident
bird. As written, a non-bird leaves every bird class low and the pipeline's
confidence threshold falls through to Tier 3 — which is the intended behaviour.

A model with no published `label_names` falls back to the legacy path: the head
is resized to the taxonomy and, without a `MODEL_PATH`, randomly initialised.
That path now logs a loud warning, because it is exactly the configuration that
produced meaningless labels through Phases 4a–4b.

## Naming conventions

- Common names come from Wikipedia article titles (a binomial redirects to its
  English name), title-cased to ornithological convention: `Black-capped
  Chickadee`, not `Black-Capped`. Coverage is 963/964.
- Where the curated list overlaps, **its** names win. Wikipedia prefers the
  global IOC name, which would silently rename `European Starling` to `Common
  Starling` across the app and the seed data.
- The model's label map is frozen at ~2023 iNaturalist naming. `CURRENT_NAMES`
  in `build_taxonomy.py` records renames (e.g. `Picoides pubescens` →
  `Dryobates pubescens`) so the CSV shows today's name while the row stays at
  the index the model actually emits.
