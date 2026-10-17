---
title: Docs and their template copies match byte for byte
tags:
- docs
- tests
- engine
- template-local
source: ''
date: '2026-10-17'
status: current
---

# Docs and their template copies match byte for byte

docs/local-workflow.md, docs/reference.md and docs/updating.md are copied byte for byte into svod/templates/local/docs/, and tests/test_copies.py fails when a copy differs: edit the file in docs/, then copy it over the template's file in the same commit.
