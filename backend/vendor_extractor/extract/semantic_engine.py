"""
V2 Semantic Engine
==================
Ties the pieces together for a whole document set:

  classify each document  ->  match every field in every document
  ->  merge candidates across documents  ->  validate  ->  canonical result

Merging is where multi-document handling actually happens. The same field can
be found in several places with different confidence; the engine keeps the best
one, records the rest as alternatives, and reports whether the documents agreed.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from ..config_loader import CONFIG_DIR, FieldDictionary, ValidationRules
from .field_matcher import KIND_RANK, Candidate, FieldMatcher
from ..ingest.layout_engine import DocumentLayout
from ..models import Document, DocumentSet, ExtractionResult, FieldResult
from .validator import Validator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DOCUMENT CLASSIFICATION
# ---------------------------------------------------------------------------

class DocumentClassifier:
    """Scores each document against config/document_profiles.yaml."""

    def __init__(self, path: Optional[Path] = None):
        path = path or CONFIG_DIR / "document_profiles.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.profiles: dict = data.get("profiles") or {}
        self.content_weight = float(data.get("content_weight", 2.0))
        self.filename_weight = float(data.get("filename_weight", 1.0))
        self.min_score = float(data.get("min_score", 1.0))

    def classify(self, document: Document) -> tuple[str, float]:
        name = document.name.lower()
        # Only the first pages are needed to tell what a document is, and
        # scanning a 50-page attachment in full would be wasted work.
        text = "\n".join(p.text for p in document.pages[:3]).lower()

        best, best_score = "other", 0.0
        for profile, cfg in self.profiles.items():
            score = 0.0
            for kw in cfg.get("filename_keywords") or []:
                if kw.lower() in name:
                    score += self.filename_weight
            for kw in cfg.get("content_keywords") or []:
                if kw.lower() in text:
                    score += self.content_weight
            if score > best_score:
                best, best_score = profile, score

        return (best, best_score) if best_score >= self.min_score else ("other", best_score)


# ---------------------------------------------------------------------------
# ENGINE
# ---------------------------------------------------------------------------

class SemanticEngine:
    def __init__(
        self,
        dictionary: FieldDictionary,
        rules: ValidationRules,
        classifier: Optional[DocumentClassifier] = None,
    ):
        self.dictionary = dictionary
        self.rules = rules
        self.classifier = classifier or DocumentClassifier()
        self.validator = Validator(rules)

        all_labels = {
            lbl.lower().strip()
            for spec in dictionary
            for lbl in spec.labels
        }
        self.matcher = FieldMatcher(list(dictionary), all_labels)

    # -- main ---------------------------------------------------------------

    def extract(self, doc_set: DocumentSet) -> ExtractionResult:
        result = ExtractionResult()

        # 1. classify + match, per document
        per_document: list[tuple[str, str, dict[str, list[Candidate]]]] = []
        for document in doc_set:
            doc_type, score = self.classifier.classify(document)
            layout = DocumentLayout(document)
            candidates = self.matcher.match_document(layout, doc_type)
            per_document.append((document.name, doc_type, candidates))
            result.documents.append(
                {
                    "document": document.name,
                    "doc_type": doc_type,
                    "classification_score": round(score, 2),
                    "pages": len(document.pages),
                    "spans": len(document.spans),
                    "fields_found": len(candidates),
                    "extraction_methods": document.metadata.get("extraction_methods", []),
                }
            )
            logger.info("%s -> %s (%d fields)", document.name, doc_type, len(candidates))

        # 2. merge across documents
        pooled: dict[str, list[Candidate]] = {}
        doc_types: dict[str, str] = {}
        for doc_name, doc_type, candidates in per_document:
            doc_types[doc_name] = doc_type
            for key, items in candidates.items():
                pooled.setdefault(key, []).extend(items)

        precedence = self.rules.cross_document.source_precedence

        for spec in self.dictionary:
            items = sorted(pooled.get(spec.key, []), key=lambda c: -c.score)
            field_result = FieldResult(key=spec.key)

            if items:
                items = self._apply_validation_bias(spec, items)
                best = self._choose(items, spec, doc_types, precedence)
                field_result.value = best.value
                field_result.confidence = best.score
                field_result.source_document = best.source_document
                field_result.source_page = best.page
                field_result.matched_label = best.matched_label
                field_result.match_kind = best.match_kind
                field_result.notes = list(best.notes)
                field_result.alternatives = [
                    c.to_dict() for c in items[:6] if c is not best
                ][:5]
            elif spec.default:
                field_result.value = spec.default
                field_result.confidence = 1.0
                field_result.source_document = "config_default"
                field_result.notes.append("filled_from_config_default")

            result.fields[spec.key] = field_result

        # 3. validate (after every value is known, so derived rules can see them)
        values = {k: (r.value or "") for k, r in result.fields.items()}
        for spec in self.dictionary:
            field_result = result.fields[spec.key]

            if not field_result.is_present:
                field_result.validation_status = "missing"
                if spec.required:
                    self._flag(result, spec.key, "missing_required_field", field_result.confidence)
                continue

            findings = self.validator.check(spec.validators, field_result.value or "", values)
            field_result.validation_status = self.validator.status_of(findings)
            field_result.validation_messages = [
                f"{f.validator}: {f.message}" for f in findings if not f.ok
            ]

            if field_result.validation_status == "invalid":
                # A configured default is a better answer than a value already
                # known to be wrong -- country is "India" far more reliably
                # than whatever sat beside the word "Country" on page 4.
                if spec.default:
                    field_result.notes.append(
                        f"replaced_invalid_value_{field_result.value!r}_with_config_default"
                    )
                    field_result.value = spec.default
                    field_result.validation_status = "valid"
                    field_result.source_document = "config_default"
                    field_result.source_page = None
                    field_result.matched_label = None
                    field_result.validation_messages = []
                    values[spec.key] = spec.default
                    continue
                self._flag(result, spec.key, "failed_validation", field_result.confidence,
                           detail="; ".join(field_result.validation_messages))
            elif field_result.validation_status == "warning":
                self._flag(result, spec.key, "validation_warning", field_result.confidence,
                           detail="; ".join(field_result.validation_messages), severity="warning")

            if field_result.confidence < spec.confidence.min_accept:
                self._flag(result, spec.key, "low_confidence", field_result.confidence)

        # 4. cross-document consistency
        for spec in self.dictionary:
            if not spec.cross_document_consistency:
                continue
            field_result = result.fields[spec.key]
            best_per_doc: dict[str, str] = {}
            # Only compare candidates the engine would actually have trusted.
            # Including rejects turns every low-scoring stray span into a
            # "documents disagree" warning and buries the real conflicts.
            trusted = [
                c for c in sorted(pooled.get(spec.key, []), key=lambda c: -c.score)
                if c.score >= spec.confidence.min_accept
            ]
            for cand in trusted:
                best_per_doc.setdefault(cand.source_document, cand.value)

            status, disagreements = self.validator.compare_across_documents(best_per_doc)
            field_result.consistency = status
            if status == "inconsistent":
                self._flag(
                    result, spec.key, "cross_document_mismatch", field_result.confidence,
                    detail="; ".join(disagreements), severity="warning",
                )

        return result

    # -- helpers ------------------------------------------------------------

    def _apply_validation_bias(self, spec, items: list[Candidate]) -> list[Candidate]:
        """Let the field's own validators influence which candidate wins.

        Validation used to run only after selection, which meant a value that
        could never be correct still won on layout evidence alone -- the state
        field picked up OCR debris ("Rvic") over the genuine "West Bengal"
        sitting a few points lower. Checking each candidate first turns those
        rules into selection signal, which is exactly the knowledge they encode.

        Derived rules are skipped here: they compare fields against each other
        and nothing is decided yet, so they have nothing to judge.
        """
        checkable = [
            name for name in spec.validators
            if self.rules.validators[name].type != "derived"
        ]
        if not checkable:
            return items

        for cand in items:
            findings = self.validator.check(checkable, cand.value, {})
            if any(not f.ok and f.severity == "error" for f in findings):
                cand.score *= 0.35
                cand.notes.append("failed_validation")
            elif any(not f.ok for f in findings):
                cand.score *= 0.75
                cand.notes.append("validation_warning")
            elif findings:
                cand.score = min(1.0, cand.score + 0.10)
                cand.notes.append("passed_validation")

        return sorted(items, key=lambda c: -c.score)

    def _choose(
        self,
        items: list[Candidate],
        spec,
        doc_types: dict[str, str],
        precedence: list[str],
    ) -> Candidate:
        """Pick the winning candidate.

        Score decides, except when candidates are effectively tied -- and they
        often are, because scores clamp at 1.0. Ties break on:

        1. The field's own `expected_documents`. This has to outrank the global
           precedence list: that list puts the Udyam certificate above the
           cheque (right for identity fields), but the Udyam certificate also
           prints bank details, and it was winning IFSC and account number away
           from the cancelled cheque that the field explicitly expects.
        2. The global source precedence, for everything with no such preference.
        3. How the value was found -- inline beats adjacent beats bare pattern.
        """
        best = items[0]
        close = [c for c in items if best.score - c.score <= 0.05]
        if len(close) <= 1:
            return best

        def expected_rank(c: Candidate) -> int:
            dtype = doc_types.get(c.source_document, "other")
            if spec.expected_documents:
                return 0 if dtype in spec.expected_documents else 1
            return 0

        def global_rank(c: Candidate) -> int:
            dtype = doc_types.get(c.source_document, "other")
            return precedence.index(dtype) if dtype in precedence else len(precedence)

        close.sort(
            key=lambda c: (
                expected_rank(c),
                global_rank(c),
                KIND_RANK.get(c.match_kind, 9),
                -c.score,
            )
        )
        return close[0]

    def _flag(
        self,
        result: ExtractionResult,
        field_key: str,
        reason: str,
        confidence: float,
        detail: str = "",
        severity: str = "error",
    ) -> None:
        entry = {
            "field": field_key,
            "reason": reason,
            "confidence": round(confidence, 4),
            "severity": severity,
        }
        if detail:
            entry["detail"] = detail
        result.needs_review.append(entry)
