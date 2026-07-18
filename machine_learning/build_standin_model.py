"""Build a *stand-in* TFLite model for hardware/pipeline smoke-testing.

This is NOT the real INatVision classifier. It exists only so the Tier-1
code path (`raspberry_pi_code/classification/tier1_tflite.py`) can be exercised
end-to-end on real hardware when the real model is unavailable:

  * input  : (1, 224, 224, 3) uint8   — matches _INPUT_SIZE and the "8bit" uint8 path
  * output : (1, N) uint8              — N = number of rows in taxonomy.csv

Its predictions are meaningless (random weights); its purpose is to prove the Pi
can load a TFLite model, preprocess a captured image, invoke the interpreter,
and produce an argmax → taxonomy mapping within a measurable latency/thermal budget.

Usage:  python machine_learning/build_standin_model.py
Requires TensorFlow (only for authoring; the Pi runtime uses tflite_runtime).
"""
import csv
from pathlib import Path

import numpy as np
import tensorflow as tf

HERE = Path(__file__).parent
TAXONOMY = HERE / "taxonomy.csv"
OUT = HERE / "stand_in_smoketest_224_uint8.tflite"


def num_classes() -> int:
    with open(TAXONOMY, newline="", encoding="utf-8") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def main() -> None:
    n = num_classes()
    model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(224, 224, 3), dtype=tf.float32),
        tf.keras.layers.Rescaling(1.0 / 255),
        tf.keras.layers.Conv2D(8, 3, strides=4, activation="relu"),
        tf.keras.layers.GlobalAveragePooling2D(),
        tf.keras.layers.Dense(n, activation="softmax"),
    ])

    def rep_dataset():
        for _ in range(20):
            yield [np.random.randint(0, 256, (1, 224, 224, 3)).astype(np.float32)]

    conv = tf.lite.TFLiteConverter.from_keras_model(model)
    conv.optimizations = [tf.lite.Optimize.DEFAULT]
    conv.representative_dataset = rep_dataset
    conv.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    conv.inference_input_type = tf.uint8
    conv.inference_output_type = tf.uint8

    tflite_model = conv.convert()
    OUT.write_bytes(tflite_model)
    print(f"Wrote {OUT} ({len(tflite_model)} bytes), {n} classes, uint8 in/out")


if __name__ == "__main__":
    main()
