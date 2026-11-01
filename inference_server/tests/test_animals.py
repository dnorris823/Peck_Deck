"""Tier 2's animal answer, without torch: the CSV, the index, and the pick.

``best_animal`` reads the same softmax as the bird answer. A plain list stands
in for the probability tensor, since both index the same way.
"""
import csv
from pathlib import Path

from inference_server.classifier import (
    AnimalPrediction,
    animal_index,
    best_animal,
    load_animals,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FEEDER_ANIMALS = REPO_ROOT / "machine_learning" / "feeder_animals.csv"
TAXONOMY = REPO_ROOT / "machine_learning" / "taxonomy.csv"

_ROWS = [
    {"scientific_name": "Sciurus carolinensis", "common_name": "Eastern Gray Squirrel", "group": "squirrel"},
    {"scientific_name": "Procyon lotor", "common_name": "Raccoon", "group": "raccoon"},
]


def test_animal_index_matches_on_scientific_name_and_skips_the_rest():
    labels = ["Cardinalis cardinalis", "procyon lotor ", "Quercus alba", "Sciurus carolinensis"]

    index = animal_index(labels, _ROWS)

    assert {i: row["group"] for i, row in index.items()} == {1: "raccoon", 3: "squirrel"}


def test_best_animal_takes_the_highest_listed_probability():
    index = animal_index(["Cardinalis cardinalis", "Procyon lotor", "Sciurus carolinensis"], _ROWS)
    probs = [0.05, 0.15, 0.80]

    assert best_animal(probs, index) == AnimalPrediction(
        "Eastern Gray Squirrel", "Sciurus carolinensis", "squirrel", 0.80
    )


def test_best_animal_is_none_without_an_index():
    assert best_animal([0.9, 0.1], {}) is None


def test_a_missing_animal_list_means_no_animals(tmp_path):
    assert load_animals(tmp_path / "nope.csv") == []


def test_the_shipped_list_loads_with_every_starting_group():
    rows = load_animals(FEEDER_ANIMALS)

    assert {r["group"] for r in rows} == {
        "squirrel", "chipmunk", "raccoon", "opossum", "deer", "bear", "cat", "rat", "rabbit",
    }
    assert all(r["common_name"] and r["scientific_name"] for r in rows)
    names = [r["scientific_name"].lower() for r in rows]
    assert len(names) == len(set(names)), "a species listed twice"


def test_no_feeder_animal_is_in_the_bird_taxonomy():
    # taxonomy.csv is Tier 1's index contract and holds birds only. An animal
    # there would also be a bird answer, and the two would compete.
    with open(TAXONOMY, newline="", encoding="utf-8") as fh:
        birds = {
            f"{r.get('genus', '').strip()} {r.get('species', '').strip()}".lower()
            for r in csv.DictReader(fh)
        }
    with open(FEEDER_ANIMALS, newline="", encoding="utf-8") as fh:
        animals = {r["scientific_name"].strip().lower() for r in csv.DictReader(fh)}

    assert not animals & birds
