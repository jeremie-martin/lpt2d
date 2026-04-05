# Roadmap Guidelines

This document describes what a good roadmap should be for this project.

It is not an implementation plan. It is guidance for writing and revising
[ROADMAP.md](/home/holo/prog/lpt2d/ROADMAP.md) in a way that stays aligned
with the project's identity and the planning discussions that shaped it.

## What A Roadmap Is For

A roadmap should define:
- what the project should become next
- why those directions matter
- how the phases relate to each other strategically

A roadmap is not primarily for implementation detail. Its job is to make the
direction of the project legible.

If the roadmap is good, someone can come back to it later and still understand:
- what the current stage of the project is
- what the next priorities are
- why those priorities come first
- what is intentionally deferred

## What This Project's Roadmap Must Reflect

The roadmap should stay faithful to the project's identity:

- physically accurate optics are non-negotiable
- physical correctness serves beauty, not pedagogy
- the goal is to make it easy to create many beautiful animations procedurally
- the Python API is the primary authored surface
- the GUI, JSON format, and Python API should feel like one coherent tool

The roadmap should also reflect the current maturity level of the project.
It should not talk as if the engine is still missing the basics if those basics
have already been built.

## What A Good Roadmap Should Be

A good roadmap for this repo should be:

- Strategic, not just operational
- Focused on `what` and `why`, not mostly on `how`
- Organized into phases with clear logic and ordering
- Explicit about the current center of gravity
- Detailed in the near term, broader in the long term
- Explicit enough to be useful when revisited later
- Flexible enough to leave room for good implementation decisions later
- Grounded in actual workflow pain points and real project needs
- Consistent with the project's design constraints
- Honest about what is core, what is cross-cutting, and what is intentionally deferred
- Written so the near-term phases read like outcomes, not only principles

## What A Good Roadmap Should Not Be

A good roadmap should not be:

- a changelog
- a backlog dump
- a pure architecture memo
- a wishlist with no prioritization
- a frozen specification of implementation mechanics
- a collection of vague aspirations with no phase structure

If a document mostly answers "how would we code this?" instead of
"what should the project become next, and why?", it is probably not yet the
right kind of roadmap.

## How To Structure It

The roadmap should usually include:

1. Project identity and current context
2. A short statement of what the roadmap is trying to do
3. A phase-based structure
4. An explicit statement of which phase is the detailed next phase, when that is clear
5. Early phases written with more precision
6. Later phases written more broadly
7. Design constraints that stay true across all phases
8. Cross-cutting concerns that matter, but are not themselves roadmap phases

Each phase should communicate:
- the problem it is responding to
- what we want from that phase
- why it should happen before the following phases
- what phase-level success or exit would look like

When a phase is evolving the core authored model, round-trip confidence and
pragmatic migration should usually live inside that phase rather than being
hidden as background maintenance.

## Good Scope Discipline

The roadmap should distinguish between three kinds of things:

### Main roadmap phases

These are major strategic directions that define the next chapter of the
project.

### Cross-cutting disciplines

These matter continuously but do not need to dominate the roadmap structure.
Examples include benchmark discipline, regression confidence, or pragmatic
migration discipline.

If one of these becomes the dominant pain point, it can be promoted into the
main roadmap structure in a later revision.

### Long-term dreams

These are valuable, but should stay explicitly long-term until the earlier
foundations that enable them are in place.

## Writing Style

The best roadmap style for this project is:

- direct
- concrete
- high-level
- explanatory

It should say enough to clarify intent, but not so much that it hard-codes the
implementation too early.

Near-term phases should usually be written with:
- a clear statement of the problem
- a clear statement of what success would look like

When describing changes to the core authored model, prefer language about
stable identity and preserved meaning over vague convenience phrasing.

When a phase is about iteration, name the comparison workflows that make
iteration real rather than talking only about generation.

Later phases can stay more open, as long as their purpose is still clear.

## Sanity Check

Before accepting a roadmap revision, ask:

- Does it clearly describe what the project should become next?
- Does it make the current center of gravity explicit?
- Does it explain why these phases are ordered this way?
- Does it match the project's identity?
- Is it detailed enough to be useful later?
- Is it restrained enough to avoid premature implementation decisions?
- Does it distinguish real roadmap phases from ongoing engineering discipline?

If the answer to those questions is yes, the roadmap is probably doing its job.
