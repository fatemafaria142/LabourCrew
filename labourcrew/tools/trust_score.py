from __future__ import annotations

from labourcrew.schemas import Claim
from labourcrew.tools.text_utils import normalize_ws
from statutegraph.schema import EvidencePack

CITATION_VALIDITY_WEIGHT = 0.35
QUOTE_FIDELITY_WEIGHT = 0.25
PROVENANCE_WEIGHT = 0.20
SELF_CONFIDENCE_WEIGHT = 0.20

assert (
    abs(CITATION_VALIDITY_WEIGHT + QUOTE_FIDELITY_WEIGHT + PROVENANCE_WEIGHT + SELF_CONFIDENCE_WEIGHT - 1.0)
    < 1e-9
)


def compute_trust_score(claim: Claim, evidence_pack: EvidencePack) -> float:
    """Weighted composite in [0, 1]; higher = more trustworthy.

    - citation_validity: fraction of cited node_ids that exist in the pack
    - quote_fidelity: fraction of cited spans found verbatim in their node's
      text (an empty span is unverifiable, not free credit -> counts as 0)
    - provenance: mean Milvus provenance_score of cited nodes that exist
    - self_confidence: the advocate's own reported `claim.confidence`,
      clipped to [0, 1]

    A claim with no evidence at all scores 0.0 -- it cannot be trusted by
    construction, independent of calibration.
    """
    if not claim.evidence:
        return 0.0

    text_by_id = {n.node_id: n.verbatim_text for n in evidence_pack.nodes}
    provenance_by_id = {n.node_id: n.provenance_score for n in evidence_pack.nodes}

    n_refs = len(claim.evidence)
    valid_refs = [ref for ref in claim.evidence if ref.node_id in text_by_id]
    citation_validity = len(valid_refs) / n_refs

    quote_hits = sum(
        1 for ref in valid_refs if ref.span and normalize_ws(ref.span) in normalize_ws(text_by_id[ref.node_id])
    )
    quote_fidelity = quote_hits / n_refs

    provenance = (
        sum(provenance_by_id[ref.node_id] for ref in valid_refs) / len(valid_refs) if valid_refs else 0.0
    )

    self_confidence = max(0.0, min(1.0, claim.confidence))

    return (
        CITATION_VALIDITY_WEIGHT * citation_validity
        + QUOTE_FIDELITY_WEIGHT * quote_fidelity
        + PROVENANCE_WEIGHT * provenance
        + SELF_CONFIDENCE_WEIGHT * self_confidence
    )
