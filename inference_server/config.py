import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8001"))
    # timm model name, or "custom" to load from MODEL_PATH
    MODEL_NAME: str = os.getenv("MODEL_NAME", "tf_efficientnet_b4.ns_jft_in1k")
    # path to .pth weights file; when set, loaded on top of the model architecture
    MODEL_PATH: str | None = os.getenv("MODEL_PATH")
    # taxonomy CSV — same format as the Pi's Tier 1 taxonomy
    TAXONOMY_PATH: str = os.getenv(
        "TAXONOMY_PATH", "../machine_learning/taxonomy.csv"
    )
    # input image size expected by the model (square)
    IMAGE_SIZE: int = int(os.getenv("IMAGE_SIZE", "380"))
    # "cuda", "cuda:0", or "cpu"
    DEVICE: str = os.getenv("DEVICE", "cuda")


settings = Settings()
