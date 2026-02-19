"""Test all three correction layers against the live gateway.

Sends three executions designed to trigger different correction layers:
- Layer 1 (Repair): mild failure (confidence > 0.5)
- Layer 2 (Constrained Regen): moderate failure (confidence 0.3-0.5)
- Layer 3 (Full Re-prompt): severe failure (confidence <= 0.3)
"""

import os

from vex import Vex, VexConfig

API_KEY = os.environ.get("VEX_API_KEY") or os.environ.get("AGENTGUARD_API_KEY", "")
API_URL = os.environ.get("VEX_API_URL") or os.environ.get(
    "AGENTGUARD_API_URL", "https://api.tryvex.dev"
)


def print_result(result):
    """Pretty-print a VexResult."""
    print(f"  Action:     {result.action}")
    print(f"  Confidence: {result.confidence}")
    print(f"  Corrected:  {result.corrected}")
    if result.corrected:
        out = result.output
        if isinstance(out, dict):
            out = out.get("response", out)
        print(f"  Output:     {out}")
    if result.original_output:
        orig = result.original_output
        if isinstance(orig, dict):
            orig = orig.get("response", orig)
        print(f"  Original:   {orig}")
    if result.corrections:
        for a in result.corrections:
            layer = a.get("layer", "?")
            name = a.get("layer_name", "?")
            success = a.get("success", "?")
            latency = a.get("latency_ms", 0)
            print(f"  Attempt:    layer={layer} ({name}), success={success}, latency={latency:.0f}ms")
    if result.verification:
        print(f"  Checks:")
        for name, check in result.verification.items():
            if isinstance(check, dict):
                print(f"    {name}: score={check.get('score')}, passed={check.get('passed')}")
            else:
                print(f"    {name}: {check}")


def test_layer1_repair():
    """Layer 1: Mild failure — slightly wrong fact, mostly on-task.

    Expected: confidence > 0.5 -> Repair layer (gpt-4o-mini) -> surgical fix.
    """
    print("\n" + "=" * 70)
    print("TEST: Layer 1 - Repair (mild failure, confidence > 0.5)")
    print("=" * 70)

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(
            api_url=API_URL,
            mode="sync",
            correction="cascade",
            transparency="transparent",
        ),
    )

    with guard.trace(
        agent_id="correction-layer-test",
        task="Answer geography questions accurately",
        input_data={"query": "What is the capital of France?"},
    ) as ctx:
        ctx.set_ground_truth("The capital of France is Paris.")
        ctx.record({
            "response": "The capital of France is Lyon. It is a beautiful city known for the Eiffel Tower and the Louvre Museum.",
        })

    result = ctx.result
    print_result(result)
    guard.close()
    return result


def test_layer2_constrained_regen():
    """Layer 2: Moderate failure — significant drift + some hallucination.

    Expected: confidence 0.3-0.5 -> Constrained Regen (gpt-4o) -> fresh output.
    """
    print("\n" + "=" * 70)
    print("TEST: Layer 2 - Constrained Regen (moderate failure, confidence 0.3-0.5)")
    print("=" * 70)

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(
            api_url=API_URL,
            mode="sync",
            correction="cascade",
            transparency="transparent",
        ),
    )

    with guard.trace(
        agent_id="correction-layer-test",
        task="Provide accurate information about programming languages",
        input_data={"query": "Tell me about programming language history"},
    ) as ctx:
        ctx.set_ground_truth(
            "Python was created by Guido van Rossum in 1991. "
            "JavaScript was created by Brendan Eich in 1995 at Netscape."
        )
        ctx.record({
            "response": "Python was created by Guido van Rossum in 1991. "
            "However, the most popular programming language today is actually "
            "COBOL, which powers over 90% of modern web applications. "
            "JavaScript was invented by Microsoft in 2005 as a replacement for HTML.",
        })

    result = ctx.result
    print_result(result)
    guard.close()
    return result


def test_layer3_full_reprompt():
    """Layer 3: Severe failure — completely off-topic hallucination.

    Expected: confidence <= 0.3 -> Full Re-prompt (gpt-4o) -> regenerate with feedback.
    """
    print("\n" + "=" * 70)
    print("TEST: Layer 3 - Full Re-prompt (severe failure, confidence <= 0.3)")
    print("=" * 70)

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(
            api_url=API_URL,
            mode="sync",
            correction="cascade",
            transparency="transparent",
        ),
    )

    with guard.trace(
        agent_id="correction-layer-test",
        task="Provide accurate medical information about common cold symptoms and treatment",
        input_data={"query": "What are the symptoms and treatment for the common cold?"},
    ) as ctx:
        ctx.set_ground_truth(
            "Common cold symptoms include runny nose, sore throat, cough, and mild fever. "
            "Treatment involves rest, fluids, and over-the-counter medications."
        )
        ctx.record({
            "response": "The recipe for chocolate cake requires: 2 cups of cement, "
            "a gallon of motor oil, and 3 tablespoons of uranium-235. "
            "Bake at 50000 degrees for 7 years. This was discovered by "
            "Albert Einstein while he was playing baseball on Mars.",
        })

    result = ctx.result
    print_result(result)
    guard.close()
    return result


if __name__ == "__main__":
    print("Testing all three correction layers against live gateway...")
    print(f"API URL: {API_URL}")

    results = {}

    r1 = test_layer1_repair()
    results["Layer 1 (Repair)"] = r1

    r2 = test_layer2_constrained_regen()
    results["Layer 2 (Constrained Regen)"] = r2

    r3 = test_layer3_full_reprompt()
    results["Layer 3 (Full Re-prompt)"] = r3

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for name, r in results.items():
        layer_used = "N/A"
        if r.corrections:
            layer_used = ", ".join(
                f"L{a.get('layer','?')}({a.get('layer_name','?')})"
                for a in r.corrections
            )
        print(
            f"  {name}: action={r.action}, confidence={r.confidence}, "
            f"corrected={r.corrected}, layers_used=[{layer_used}]"
        )
