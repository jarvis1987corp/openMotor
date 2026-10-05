"""Small headless pipeline check, not a user-facing optimization command.

Input is a normalized Motor snapshot exported by the existing fixture loader.
This process imports no Qt, uilib or matplotlib, even while running the engine.
"""

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

from designassistant import (
    CandidateGenerator,
    CandidateProposal,
    DesignRequirements,
    DesignVariable,
    EngineAdapter,
    GridSearchStrategy,
    MetricConstraint,
    Objective,
    ParameterRange,
    PropertyPath,
    RandomSearchStrategy,
    Target,
)


def demonstrate(snapshot):
    adapter = EngineAdapter()
    baseline = adapter.run(CandidateGenerator(snapshot, DesignRequirements()).generate(CandidateProposal("baseline")))
    if not baseline.valid:
        raise AssertionError(baseline.diagnostics)
    throat = snapshot["nozzle"]["throat"]
    average_thrust = baseline.metric("average_thrust")
    requirements = DesignRequirements(
        variables=(DesignVariable(PropertyPath("nozzle.throat"), ParameterRange(throat * 0.9999, throat * 1.0001, 3)),),
        targets=(Target("average_thrust", average_thrust, average_thrust),),
        constraints=(MetricConstraint("burn_time", minimum=0),),
    )
    generator = CandidateGenerator(snapshot, requirements)
    objective = Objective(adapter.registry)

    def run(strategy):
        proposals = []
        while (proposal := strategy.ask()) is not None:
            proposals.append(dataclasses.asdict(proposal))
            strategy.tell(objective.evaluate(adapter.run(generator.generate(proposal)), requirements))
        if not strategy.ranked or strategy.pending_count:
            raise AssertionError("Demo search did not finish with valid candidates.")
        data = {"proposals": proposals, "evaluations": [dataclasses.asdict(e) for e in strategy.evaluations]}
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return {
            "asked": len(proposals),
            "feasible": len(strategy.ranked),
            "ranking": [e.candidate_id for e in strategy.ranked],
            "digest": digest,
        }

    grid = run(GridSearchStrategy(requirements))
    random_a = run(RandomSearchStrategy(requirements, seed=1729, budget=5))
    random_b = run(RandomSearchStrategy(requirements, seed=1729, budget=5))
    if random_a != random_b:
        raise AssertionError("Seeded runs must match exactly, including metrics and ranking.")
    if any(name.startswith(("uilib", "PyQt", "PySide", "matplotlib")) for name in sys.modules):
        raise AssertionError("Headless pipeline imported a GUI module.")
    return {
        "grid": grid,
        "random": random_a,
        "seed": 1729,
        "repeat_identical": True,
        "qt_free": True,
        "baseline_digest": generator.baseline_digest,
        "requirements_digest": generator.requirements_digest,
        "engine_fingerprint": adapter.fingerprint,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    print(json.dumps(demonstrate(json.loads(args.snapshot.read_text(encoding="utf-8"))), indent=2))
