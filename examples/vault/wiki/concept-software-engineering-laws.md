---
tags: [concept, software-engineering]
date: 2026-06-25
source_count: 2
---

# Software-engineering laws

A **diagnostic vocabulary**: the ~56 named "laws" that recur across software work, catalogued in full in [[src-laws-of-software-engineering]]. They are not physical constants. Every one has exceptions; their worth is as warning lights and as shared names for forces you would otherwise have to re-describe each time. Naming the force is half of handling it.

## The seven families
The source page lists them all; the shape of each family:
- **Architecture** : structure follows communication (Conway), complexity is conserved (Tesler) and leaks (Leaky Abstractions), and every observable behaviour eventually gets depended on (Hyrum).
- **Teams** : adding people to a late project makes it later (Brooks); per-head output falls as groups grow (Ringelmann).
- **Planning** : work expands to fill the time (Parkinson); estimates run long even when you account for that (Hofstadter); a measure that becomes a target stops measuring (Goodhart).
- **Quality** : leave code cleaner than you found it (Boy Scout), small decay compounds (Broken Windows), debugging is harder than writing (Kernighan).
- **Scale** : the sequential fraction caps the speedup (Amdahl); network value grows with users (Metcalfe).
- **Design principles** : YAGNI, DRY (tempered by the rule of three), KISS, SOLID, Least Astonishment : rules of thumb that deliberately pull against each other.
- **Decision-making** : mostly cognitive traps (Sunk Cost, Confirmation Bias, Occam, Hanlon, Map Is Not the Territory).

## Why a concept layer above the list
The laws share a backbone: **complexity is conserved, measurement corrupts under pressure, structure mirrors the organisation that built it, and most bad technical calls are bad reasoning in technical dress.** Taken together they are less a rulebook than a checklist for naming what is going wrong before reaching for a fix. The source lesson's own caution applies: design principles and decision rules pull in different directions on purpose, and the skill is knowing which one applies now, not applying all at once.

## Bridges to the AI cluster
Several laws are the software-engineering face of ideas elsewhere in this vault, which is why they recur under concept-trusting-the-surface:
- **Goodhart's Law** (a measure that becomes a target stops being a good measure) is the same failure as benchmark gaming and search-time contamination (src-search-time-contamination) and the gameable-metric ceiling of self-improving agents (concept-self-improving-agents, src-hyperagents-dgm).
- **Map Is Not the Territory** : the model, the metric, the valid form is not the real outcome : is exactly the constraint tax, where a schema-valid answer can still be wrong (src-constraint-tax, concept-structured-output).
- **Hyrum's Law / Postel's Law** (every observable behaviour gets depended on; be liberal in what you accept) frame why an agent must treat all read input as untrusted (src-agentredbench) and stay robust to messy, underspecified users (concept-agent-failure-modes).

## The AI abstraction shift

src-uncle-bob-software-fundamentals-ai argues that agents change the labour economics, not the underlying complexity. Faster implementation makes previously expensive disciplines such as mutation testing and repeated structural cleanup practical, while modularity and dependency direction still make the system locally conceivable. In this framing, the laws are useful to an agent supervisor for the same reason they were useful to a programmer: they name conserved forces before a locally plausible change spreads them elsewhere.

## Caveat
The source lesson flags several attributions and figures (Dunbar's number, Price's Law, the Dilbert Principle, Dunning-Kruger, Lehman's full set) as worth verifying before formal use; the extended explanations on the source page are original to the lesson, not independently cross-referenced. Martin's abstraction argument is also practitioner judgement rather than a measured result.
