"""Agent-driven supply-assurance demo — companion service.

This package is a STANDALONE FastAPI service that lives alongside the
Knowledge Fabric backend but talks to it over HTTP. The investigation
flow is scripted (deterministic for demo day); the LLM is only used
for short narration lines between steps so the audience feels the
reasoning without depending on a tool-use loop on demo day.

See /Users/abigailcharles/.claude/plans/ok-i-need-a-steady-gray.md
for the full design + rationale.
"""
