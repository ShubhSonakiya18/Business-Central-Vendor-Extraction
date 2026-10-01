"""The 5-prompt benchmark suite. Real prompt TEXT (not synthetic filler) so
TTFT and per-prompt latency reflect an actual request shape, per the
requirement to not benchmark only synthetic "Hello world" inputs.

Output lengths are deliberately moderate (not maximal) -- an explicit,
documented scope reduction to keep total benchmark wall-clock reasonable
given this model's measured ~1-1.5 tok/s on this machine (see
CPU_BENCHMARK_REPORT.md, Methodology). This does NOT distort the reported
RATE (tokens/sec) -- that metric is scale-invariant; a shorter generation
measures the same steady-state throughput as a longer one, just faster to
collect. It only limits how far into a response we measure, which is stated
plainly wherever these numbers are reported.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BenchPrompt:
    id: str
    category: str
    text: str
    max_tokens: int


LONG_PROMPT_FILLER = (
    "The history of long-distance trade in the Indian subcontinent stretches back "
    "millennia, with overland caravan routes connecting the Gangetic plain to Central "
    "Asia, and maritime routes linking the Malabar and Coromandel coasts to East Africa, "
    "the Arabian Gulf, and Southeast Asia. Ports such as Muziris, Kalyan, and later "
    "Surat and Masulipatnam served as hubs where textiles, spices, gemstones, and "
    "metalwork changed hands between merchants of many origins. Guild structures, "
    "known variously as shreni in classical sources, regulated craft production, set "
    "quality standards, and negotiated collectively with rulers over taxation and "
    "market access. Coinage systems evolved alongside this trade, from punch-marked "
    "silver coins of the Mauryan period through the gold dinars of the Gupta era to "
    "the diverse regional currencies of the medieval sultanates. "
) * 6  # repeated to build a long, still-coherent input without hand-writing 600 words


PROMPTS: list[BenchPrompt] = [
    BenchPrompt(
        id="short_short",
        category="Short prompt / short output",
        text="What is the capital of France?",
        max_tokens=20,
    ),
    BenchPrompt(
        id="medium_medium",
        category="Medium prompt / medium output",
        text=(
            "Explain, in a short paragraph, why prompt processing (reading the input) "
            "and token generation (writing the output) are measured as separate "
            "throughput numbers when benchmarking a language model, and why they can "
            "have very different tokens-per-second rates on the same hardware."
        ),
        max_tokens=50,
    ),
    BenchPrompt(
        id="long_medium",
        category="Long prompt / medium output",
        text=(
            f"{LONG_PROMPT_FILLER}\n\n"
            "In one sentence, name the two coastal regions of the Indian subcontinent "
            "mentioned above."
        ),
        max_tokens=50,
    ),
    BenchPrompt(
        id="structured_extraction",
        category="Structured extraction-style prompt",
        text=(
            "Extract the following fields from this business document text as JSON "
            "with keys vendor_name, address, gstin, pan, and pin_code. Only output the "
            "JSON object, nothing else.\n\n"
            "Text: SHIVAM FORGINGS PVT LTD, PLOT NO. 47, INDUSTRIAL AREA PHASE II, "
            "TALOJA, NAVI MUMBAI, MAHARASHTRA - 410208. GSTIN: 27AABCS1429B1ZP. "
            "PAN: AABCS1429B."
        ),
        max_tokens=60,
    ),
    BenchPrompt(
        id="reasoning",
        category="Reasoning-style prompt",
        text=(
            "A vendor invoice shows a subtotal of 12,500 rupees, an 18% GST charge, "
            "and a 2% early-payment discount applied to the subtotal before tax. "
            "Walk through the calculation step by step and give the final total."
        ),
        max_tokens=80,
    ),
]
