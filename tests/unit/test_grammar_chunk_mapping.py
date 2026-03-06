"""Validate that data/grammar_point_chunks.yaml contains all GP codes."""
import json

import pytest
import yaml

from maestro.utils import DATA_DIR

GRAMMAR_POINTS_FILE = DATA_DIR / "grammar_points.json"
CHUNK_MAPPING_FILE = DATA_DIR / "grammar_point_chunks.yaml"


@pytest.mark.unit
def test_mapping_covers_all_gp_codes():
    """Every GP code in grammar_points.json appears in grammar_point_chunks.yaml."""
    with open(GRAMMAR_POINTS_FILE) as f:
        gps = json.load(f)
    gp_codes = {gp["code"] for gp in gps}

    with open(CHUNK_MAPPING_FILE) as f:
        mapping = yaml.safe_load(f)

    mapping_codes = set(mapping.keys())
    missing = gp_codes - mapping_codes
    assert not missing, f"GP codes missing from chunk mapping: {missing}"


@pytest.mark.unit
def test_mapping_has_no_extra_codes():
    """No codes in grammar_point_chunks.yaml that aren't in grammar_points.json."""
    with open(GRAMMAR_POINTS_FILE) as f:
        gps = json.load(f)
    gp_codes = {gp["code"] for gp in gps}

    with open(CHUNK_MAPPING_FILE) as f:
        mapping = yaml.safe_load(f)

    extra = set(mapping.keys()) - gp_codes
    assert not extra, f"Extra codes in chunk mapping: {extra}"


@pytest.mark.unit
def test_each_gp_code_appears_exactly_once():
    """Every GP code appears exactly once as a key."""
    with open(CHUNK_MAPPING_FILE) as f:
        mapping = yaml.safe_load(f)

    with open(GRAMMAR_POINTS_FILE) as f:
        gps = json.load(f)
    gp_codes = {gp["code"] for gp in gps}

    assert len(mapping) == len(gp_codes)
