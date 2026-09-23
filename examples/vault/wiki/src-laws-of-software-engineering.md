---
tags: [source, software-engineering, reference]
date: 2026-06-11
source_count: 1
---

# Source: Laws of Software Engineering — A Landscape Tour

Concept roll-up: [[concept-software-engineering-laws]] (the seven families and the bridges into the AI cluster).

Summary of [[raw/laws-of-software-engineering-lesson]]. A tour of ~56 named "laws" across seven categories, structured around the collection at lawsofsoftwareengineering.com by Dr. Milan Milanović. These are repeatable patterns and warning lights, not physical constants — every one has exceptions; their value is as a diagnostic vocabulary.

## 1. Architecture
- **Conway's Law** — a system mirrors the communication structure of the org that built it. (The *Inverse Conway Manoeuvre*: change team structure to change architecture.)
- **Gall's Law** — complex systems that work grew from simple systems that worked.
- **Tesler's Law** (Conservation of Complexity) — every system has irreducible complexity; you move it, you can't delete it.
- **Law of Leaky Abstractions** — all non-trivial abstractions leak.
- **CAP Theorem** — a distributed store gives at most two of consistency, availability, partition tolerance.
- **Hyrum's Law** — with enough users, every observable behaviour (including bugs) gets depended on.
- **Fallacies of Distributed Computing** — eight false assumptions (network is reliable, latency zero, bandwidth infinite, etc.).
- **Second-System Effect**, **Zawinski's Law** (every program expands until it can read email).

## 2. Teams
- **Brooks's Law** — adding people to a late project makes it later.
- **Ringelmann Effect** — per-person productivity drops as groups grow.
- **Dunbar's Number** (~150, really a range), **Price's Law** (√group does half the work), **Bus Factor**, **Peter Principle**, **Dilbert Principle**, **Putt's Law**.

## 3. Planning
- **Parkinson's Law** — work expands to fill available time.
- **Hofstadter's Law** — it always takes longer than you expect, even accounting for this.
- **Ninety-Ninety Rule**, **Knuth's** "premature optimization is the root of all evil" (the nuance: the critical 3% does matter).
- **Goodhart's Law** — when a measure becomes a target, it stops being a good measure. **Gilb's Law** is the counterweight (imperfect measurement beats none).

## 4. Quality
Boy Scout Rule · Broken Windows · Murphy's Law · **Postel's Law** (now contested) · **Linus's Law** (enough eyeballs) · **Kernighan's Law** (debugging is twice as hard as writing) · Testing Pyramid · Pesticide Paradox · Technical Debt · **Lehman's Laws** of software evolution · Sturgeon's Law.

## 5. Scale
- **Amdahl's Law** — parallel speedup capped by the sequential fraction (20% serial → 5× ceiling).
- **Gustafson's Law** (optimistic counterpart), **Metcalfe's Law** (network value ~ users²).

## 6. Design principles
YAGNI · DRY (beware premature deduplication — rule of three) · KISS · **SOLID** · Law of Demeter · Principle of Least Astonishment.

## 7. Decision-making
Dunning-Kruger (contested) · Hanlon's Razor · Occam's Razor · Sunk Cost Fallacy · Map Is Not the Territory · Confirmation Bias · Amara's Law · Lindy Effect · First Principles · Inversion · **Pareto (80/20)** · Cunningham's Law.

## Cross-links to the AI cluster
- **Goodhart's Law** ↔ benchmark gaming and search-time contamination (src-search-time-contamination), and the gameable-metric risk of self-improvers (src-hyperagents-dgm). Central to concept-trusting-the-surface.
- **Map Is Not the Territory** ↔ a valid form / high score is not the real outcome (src-constraint-tax, concept-trusting-the-surface).
- **Hyrum's Law / Postel's Law** ↔ treating all read input as untrusted (src-agentredbench).

> Source caveat: the lesson flags many attributions and figures (Dunbar, Price, Dilbert Principle, Dunning-Kruger, Lehman's full set) as worth verifying before formal use. Extended explanations are original to the lesson, not cross-referenced.
