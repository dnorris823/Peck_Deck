import csv
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

            num_classes = len(self._taxonomy)
            self._model = timm.create_model(
                self._model_name,
                pretrained=(self._weights_path is None),
                num_classes=num_classes,
            )

            if self._weights_path:
                state = torch.load(self._weights_path, map_location=self._device)
                self._model.load_state_dict(state)

            self._model.eval()
            self._model.to(self._device)

            data_config = timm.data.resolve_model_data_config(self._model)
            self._transform = timm.data.create_transform(**data_config, is_training=False)

            logger.info(
                "Loaded model '%s' on %s (%d classes)",
                self._model_name, self._device, num_classes,
            )
            return True

        except Exception:
            logger.exception("Failed to load model '%s'", self._model_name)
            return False

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
                probs = torch.softmax(logits, dim=1)[0]
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
