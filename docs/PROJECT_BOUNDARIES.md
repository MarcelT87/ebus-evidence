# Project boundaries

`ebus-evidence` is a standalone public community evidence tool.

This document defines the project boundary so implementation from adjacent
research projects does not silently leak into this repository.

## This repository owns

`ebus-evidence` owns the implementation and public documentation for:

- parsing normal ebusd **message-mode raw logs**;
- offline analysis;
- persistent passive watch/state/resume;
- rare-event context capture;
- privacy-minimized system identity;
- observation-scope metadata;
- deterministic evidence bundles;
- bundle verification;
- evidence profiles;
- beginner/community workflows for collecting and sharing evidence safely.

All source code required for those functions belongs in this repository.

## This repository does not own

This project is not:

- a general eBUS research database;
- a historical correlation engine;
- an automatic semantic decoder;
- a replacement for ebusd;
- a direct eBUS adapter client;
- a heating-control application;
- a container for private research handoffs or local environment notes.

Do not import implementation simply because another research project has a
similar helper or decoder.

## No runtime dependency on a research lab

The public tool must remain independently installable and usable.

It must not require:

- another project's database;
- another project's Python modules;
- another project's source checkout;
- private files;
- private GitHub access;
- project-specific host paths.

A verified evidence bundle may later be consumed by external research tooling,
but that is a **data interchange boundary**, not a source-code dependency.

## What may cross the boundary

Allowed cross-project exchange is deliberately narrow:

- documented protocol facts supported by evidence;
- explicitly reviewed evidence-profile definitions;
- public format/specification decisions;
- deterministic evidence bundles;
- verifier-compatible bundle metadata;
- links to public upstream issues/PRs.

When a protocol finding from another project informs an evidence profile, the
profile change must still be reviewed and implemented **here**, with its own
tests and public documentation.

## What must not cross automatically

Do not automatically copy:

- source modules;
- database/query code;
- private handoffs;
- local paths;
- raw logs;
- generated states;
- evidence ZIPs;
- credentials;
- internal roadmaps;
- speculative semantic labels.

## Documentation ownership

This repository is authoritative for the public tool's:

- behavior;
- CLI;
- formats;
- privacy contract;
- supported workflows;
- tests;
- release state.

External/private project documentation may describe how this tool is used in a
larger research workflow, but it does not override this repository.

## No handoff files in this public repository

This repository must not contain chat handoffs, internal project-status
snapshots, private planning notes, cross-project coordination files or local
validation handoffs.

If a maintainer/chat receives such a handoff:

1. treat it only as private source/context;
2. do not commit the handoff itself here;
3. do not copy private/local details into public docs;
4. if the handoff reveals a real public-tool issue, implement only the
   sanitized code/test/documentation change that belongs to this repository;
5. keep private coordination/history in the private research project instead.

This rule also applies when a handoff describes this public tool accurately.
Correctness does not make an internal handoff public documentation.

## Handoff rule

A new maintainer/chat working on `ebus-evidence` should:

1. live-check the current `main`;
2. read this repository's README and relevant docs;
3. treat this repository as the source of truth for implementation;
4. keep the passive/read-only and privacy boundaries intact;
5. only consult external project material for research context, never as an
   implicit code dependency.
