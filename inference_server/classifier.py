import csv
import json
import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import timm
    import timm.data
    import torch
    from PIL import Image

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    logger.warning("torch/timm/Pillow not installed — classifier will be unavailable")


@dataclass
class Prediction:
    common_name: str
    scientific_name: str
    confidence: float


class BirdClassifier:
    def __init__(
        self,
        model_name: str,
        taxonomy_path: str,
        *,
        image_size: int = 380,
        weights_path: str | None = None,
        device: str = "cuda",
    ):
        self._model_name = model_name
        self._taxonomy_path = Path(taxonomy_path)
        self._image_size = image_size
        self._weights_path = weights_path
        self._requested_device = device
        self._model = None
        self._transform = None
        self._taxonomy: list[dict] = []
        self._device = None
        # model output index -> taxonomy index. Empty when the model's head was
        # built to match the taxonomy directly (the legacy path).
        self._projection: dict[int, int] = {}

    def load(self) -> bool:
        if not _TORCH_AVAILABLE:
            logger.error("torch/timm not available — cannot load classifier")
            return False

        self._taxonomy = self._load_taxonomy()
        if not self._taxonomy:
            return False

        try:
            import torch
            import timm
            import timm.data

            requested = self._requested_device
            if requested.startswith("cuda") and not torch.cuda.is_available():
                logger.warning("CUDA requested but not available — falling back to CPU")
                requested = "cpu"
            self._device = torch.device(requested)

            label_names = self._hub_label_names()

            if label_names:
                # A pretrained checkpoint with its own label space. Keep the
                # head as trained — re-heading it to len(taxonomy) would throw
                # away the very weights that make the predictions real — and
                # project its classes onto the shared taxonomy by name.
                self._model = timm.create_model(self._model_name, pretrained=True)
                self._build_projection(label_names)
                if not self._projection:
                    logger.error(
                        "No class in '%s' maps onto the taxonomy — refusing to load "
                        "a model whose predictions could not be interpreted",
                        self._model_name,
                    )
                    return False
            else:
                # Legacy path: architecture only, head sized to the taxonomy.
                # Without weights_path the head is randomly initialised and the
                # labels are meaningless — kept only so an explicitly fine-tuned
                # .pth can still be loaded.
                self._model = timm.create_model(
                    self._model_name,
                    pretrained=(self._weights_path is None),
                    num_classes=len(self._taxonomy),
                )
                if not self._weights_path:
                    logger.warning(
                        "'%s' has no published label names and no weights file — "
                        "the classification head is random and every label is "
                        "meaningless. Set MODEL_NAME to an hf-hub checkpoint or "
                        "point MODEL_PATH at fine-tuned weights.",
                        self._model_name,
                    )

            if self._weights_path:
                state = torch.load(self._weights_path, map_location=self._device)
                self._model.load_state_dict(state)

            self._model.eval()
            self._model.to(self._device)

            data_config = timm.data.resolve_model_data_config(self._model)
            self._transform = timm.data.create_transform(**data_config, is_training=False)

            logger.info(
                "Loaded model '%s' on %s (%d model classes -> %d taxonomy entries, "
                "%d mapped)",
                self._model_name, self._device,
                getattr(self._model, "num_classes", len(self._taxonomy)),
                len(self._taxonomy), len(self._projection),
            )
            return True

        except Exception:
            logger.exception("Failed to load model '%s'", self._model_name)
            return False

    def _hub_label_names(self) -> list[str] | None:
        """Scientific names for each output index, if the checkpoint ships them.

        timm records them in ``config.json`` on the Hub as ``label_names``. This
        is what makes a shared label space possible: without it the model's
        output indices are uninterpretable, and guessing an ordering would
        produce confident, plausible, wrong species.
        """
        if not self._model_name.startswith("hf-hub:"):
            return None
        repo_id = self._model_name.split("hf-hub:", 1)[1]
        try:
            from huggingface_hub import hf_hub_download

            path = hf_hub_download(repo_id=repo_id, filename="config.json")
            with open(path, encoding="utf-8") as fh:
                names = json.load(fh).get("label_names")
            if names:
                logger.info("Found %d label names for %s", len(names), repo_id)
            return names
        except Exception:
            logger.warning("Could not read label_names for %s", repo_id, exc_info=True)
            return None

    def _build_projection(self, label_names: list[str]) -> None:
        """Map model output index -> taxonomy index, matched on scientific name.

        Anything unmatched (iNat21 carries plants and insects too) stays out of
        the projection. Predictions are still softmaxed over the *full* output,
        so a squirrel at the feeder leaves every bird class with low probability
        and the pipeline's confidence threshold falls through to the next tier,
        rather than being forced into a confident bird answer.
        """
        by_name = {
            entry["scientific_name"].strip().lower(): i
            for i, entry in enumerate(self._taxonomy)
            if entry["scientific_name"].strip()
        }
        self._projection = {
            model_idx: by_name[name.strip().lower()]
            for model_idx, name in enumerate(label_names)
            if name.strip().lower() in by_name
        }
        unmapped = len(by_name) - len(set(self._projection.values()))
        if unmapped:
            logger.info(
                "%d taxonomy species have no counterpart in the model's label "
                "space; Tier 2 cannot predict those", unmapped,
            )

    def _load_taxonomy(self) -> list[dict]:
        if not self._taxonomy_path.exists():
            logger.error("Taxonomy file not found: %s", self._taxonomy_path)
            return []

        taxonomy = []
        with open(self._taxonomy_path, newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                row_lower = {k.lower(): v.strip() for k, v in row.items()}
                common = row_lower.get("common_name", "Unknown")
                genus = row_lower.get("genus", "")
                species = row_lower.get("species", "sp.")
                sci = f"{genus} {species}".strip() if genus else species
                taxonomy.append({"common_name": common, "scientific_name": sci})

        logger.info("Loaded taxonomy: %d entries from %s", len(taxonomy), self._taxonomy_path)
        return taxonomy

    def classify(self, image_bytes: bytes) -> Prediction | None:
        if self._model is None:
            return None

        try:
            import torch
            from PIL import Image

            img = Image.open(BytesIO(image_bytes)).convert("RGB")
            tensor = self._transform(img).unsqueeze(0).to(self._device)

            with torch.no_grad():
                logits = self._model(tensor)
                # Softmax across every class the model knows, then pick the best
                # one we can name. Restricting *before* the softmax would
                # renormalise a squirrel into a confident bird.
                probs = torch.softmax(logits, dim=1)[0]

                if self._projection:
                    model_indices = list(self._projection)
                    subset = probs[model_indices]
                    best = int(subset.argmax())
                    idx = self._projection[model_indices[best]]
                    confidence = float(subset[best])
                else:
                    idx = int(probs.argmax())
                    confidence = float(probs[idx])

            entry = (
                self._taxonomy[idx]
                if idx < len(self._taxonomy)
                else {"common_name": "Unknown", "scientific_name": ""}
            )
            return Prediction(
                common_name=entry["common_name"],
                scientific_name=entry["scientific_name"],
                confidence=confidence,
            )

        except Exception:
            logger.exception("Classification failed")
            return None
