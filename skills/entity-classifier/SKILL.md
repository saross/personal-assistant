---
skill_name: entity-classifier
version: 1.0.0
description: Classify dual-nature entities (hotels, churches, schools, halls) as building-only, business/organisation-only, or both based on contextual linguistic analysis.
author: Shawn Ross
tags:
  - taxonomy
  - classification
  - natural-language-processing
  - cultural-heritage
skill_type: project
---

# Entity Classifier Skill

## Purpose

Classifies mentions of dual-nature entities (hotels, churches, schools of arts, halls, lodges, etc.) in historical newspaper text to determine whether they should be tagged as:
- **Building/facility only** (Built Environment facet)
- **Business/organisation only** (Agents facet)
- **Both (polyhierarchical)** (appears in both facets)

Uses natural language understanding to analyse context and apply a linguistic heuristic framework, providing more nuanced classification than deterministic regex patterns.

## When to Use

- Classifying hotel mentions as buildings vs businesses
- Determining church classification (building vs religious organisation)
- Analysing schools of arts (venue vs cultural society)
- Any entity that can be both physical structure and organisational agent
- Reviewing and validating automated classifications
- Batch processing entity mentions from Zotero library

## Key Features

- Context-aware classification using LLM reasoning
- Applies proven linguistic heuristic (spatial vs agency indicators)
- Structured output for easy processing
- Confidence scoring
- Detailed reasoning for audit trail
- Reusable across entity types
- Handles metonymy and implied reference
- UK/Australian spelling throughout

## Output Format

**CRITICAL:** Always generate classification results as **markdown files**, never as chat responses only.

**Required output:**
- File location: `entity-tagging-system/outputs/{entity-type}/{entity-type}_classification_results.md`
- Use template: `entity-tagging-system/templates/classification-report-template.md`
- Include: detailed analysis for each mention, pattern summary, taxonomy recommendations, comparison tables

**Why markdown files:**
- Creates permanent audit trail
- Enables cross-session review
- Facilitates methodology sharing
- Supports reproducible research
- Chat responses are ephemeral; files persist

## Related Documents

- `/home/shawn/Code/blue-mountains/docs/entity-classification-heuristic.md` - Full decision framework
- `/home/shawn/Code/blue-mountains/CLAUDE.md` - Project taxonomy principles
- Getty AAT guidelines for polyhierarchical classification
