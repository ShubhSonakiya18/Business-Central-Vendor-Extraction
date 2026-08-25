"""Strict config loading.

The loader's contract is that a malformed field dictionary fails loudly at
startup, naming the offending field, rather than silently producing a blank
Excel cell discovered weeks later. Each test here asserts one of those refusals
still fires -- a loosened check would otherwise go unnoticed until it mattered.
"""

import textwrap

import pytest
import yaml

from v2.config_loader import ConfigError, load_config


@pytest.fixture
def config_dir(tmp_path):
    """A minimal but valid config tree the tests then corrupt one way at a time."""
    (tmp_path / "excel_mappings").mkdir()

    rules = {
        "validators": {
            "pan_format": {
                "type": "regex",
                "pattern": r"[A-Z]{5}[0-9]{4}[A-Z]",
                "severity": "error",
                "message": "PAN must be 5 letters, 4 digits, 1 letter",
            },
        },
        "cross_document": {
            "similarity_threshold": 0.85,
            "source_precedence": ["gst_certificate"],
            "severity": "warning",
            "message": "documents disagree",
        },
    }
    (tmp_path / "validation_rules.yaml").write_text(yaml.safe_dump(rules), encoding="utf-8")

    (tmp_path / "document_profiles.yaml").write_text(
        yaml.safe_dump({
            "settings": {"filename_weight": 1.0, "content_weight": 2.0, "min_score": 1.0},
            "profiles": {
                "gst_certificate": {
                    "filename_keywords": ["gst"],
                    "content_keywords": ["goods and services tax"],
                },
            },
        }),
        encoding="utf-8",
    )
    return tmp_path


def write_fields(config_dir, fields, defaults=None):
    doc = {"version": 1, "fields": fields}
    if defaults:
        doc["defaults"] = defaults
    (config_dir / "field_dictionary.yaml").write_text(
        yaml.safe_dump(doc), encoding="utf-8"
    )
    return config_dir


VALID_FIELD = {
    "labels": ["PAN"],
    "patterns": [r"[A-Z]{5}[0-9]{4}[A-Z]"],
    "validators": ["pan_format"],
    "confidence": {
        "weights": {
            "label_similarity": 0.35,
            "spatial_proximity": 0.25,
            "pattern_match": 0.30,
            "ocr_confidence": 0.10,
        },
    },
}


class TestAcceptsValidConfig:
    def test_loads_a_well_formed_dictionary(self, config_dir):
        write_fields(config_dir, {"pan": dict(VALID_FIELD)})
        dictionary, rules = load_config(config_dir)
        assert len(dictionary) == 1
        assert "pan_format" in rules.validators
        assert rules.cross_document.similarity_threshold == 0.85


class TestRejectsMalformedFields:
    def test_unknown_field_key(self, config_dir):
        field = dict(VALID_FIELD, colour="blue")
        write_fields(config_dir, {"pan": field})
        with pytest.raises(ConfigError, match="unknown key"):
            load_config(config_dir)

    def test_field_with_neither_labels_nor_patterns(self, config_dir):
        """A field the matcher has no way to find is a config mistake, not an
        empty result."""
        field = {k: v for k, v in VALID_FIELD.items() if k not in ("labels", "patterns")}
        write_fields(config_dir, {"pan": field})
        with pytest.raises(ConfigError):
            load_config(config_dir)

    def test_field_must_be_a_mapping(self, config_dir):
        write_fields(config_dir, {"pan": "not a mapping"})
        with pytest.raises(ConfigError, match="must be a mapping"):
            load_config(config_dir)


class TestConfidenceWeights:
    def test_weights_must_sum_to_one(self, config_dir):
        """The score is a weighted sum; weights that do not total 1.0 silently
        rescale every confidence in the system."""
        field = dict(VALID_FIELD, confidence={"weights": {
            "label_similarity": 0.5,
            "spatial_proximity": 0.5,
            "pattern_match": 0.5,
            "ocr_confidence": 0.5,
        }})
        write_fields(config_dir, {"pan": field})
        with pytest.raises(ConfigError, match="sum to"):
            load_config(config_dir)

    def test_tiny_float_error_is_tolerated(self, config_dir):
        # 0.35 + 0.25 + 0.30 + 0.10 does not land exactly on 1.0 in binary
        # floating point; the loader allows 1e-6 of slack for exactly this.
        field = dict(VALID_FIELD, confidence={"weights": {
            "label_similarity": 0.35,
            "spatial_proximity": 0.25,
            "pattern_match": 0.30,
            "ocr_confidence": 0.10,
        }})
        write_fields(config_dir, {"pan": field})
        dictionary, _ = load_config(config_dir)
        assert dictionary["pan"].confidence.min_accept == 0.6


class TestReferentialIntegrity:
    def test_validator_name_must_exist(self, config_dir):
        """A typo'd validator name would otherwise mean the field is silently
        never validated."""
        field = dict(VALID_FIELD, validators=["pan_frmat"])
        write_fields(config_dir, {"pan": field})
        with pytest.raises(ConfigError):
            load_config(config_dir)

    def test_unknown_normalization_op(self, config_dir):
        field = dict(VALID_FIELD, normalization=["uppercase", "make_it_nice"])
        write_fields(config_dir, {"pan": field})
        with pytest.raises(ConfigError):
            load_config(config_dir)

    def test_unknown_search_direction(self, config_dir):
        field = dict(VALID_FIELD, search={"directions": ["right", "diagonally"]})
        write_fields(config_dir, {"pan": field})
        with pytest.raises(ConfigError, match="direction"):
            load_config(config_dir)


class TestShippedConfig:
    """The config that actually ships must load, and must keep the invariants
    the rest of the system assumes."""

    def test_loads(self):
        dictionary, rules = load_config()
        assert len(dictionary) > 0
        assert len(rules.validators) > 0

    def test_every_field_has_a_way_to_be_found(self):
        dictionary, _ = load_config()
        for field in dictionary:
            assert field.labels or field.patterns, f"{field.key} is unfindable"

    def test_every_referenced_validator_is_defined(self):
        dictionary, rules = load_config()
        for field in dictionary:
            for name in field.validators:
                assert name in rules.validators, f"{field.key} -> {name}"

    def test_required_fields_are_declared(self):
        dictionary, _ = load_config()
        assert dictionary.required_fields, "no required fields configured"
