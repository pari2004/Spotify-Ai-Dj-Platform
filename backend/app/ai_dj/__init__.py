"""AI DJ Engine: acoustic matcher, sentiment aggregator, RAG generator, recommender.

Kept as a standalone package with pure functions (match_segue, score_sentiment,
generate_transition, resolve_battle) so every piece is unit-testable without a live
socket or database (PRD §9.3).
"""
