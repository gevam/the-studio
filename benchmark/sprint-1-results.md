# Sprint 1 Benchmark Results

**Project:** todo-cli
**Date:** 2026-06-02

## Summary

| Metric | Baseline (plain Claude) | Studio |
|--------|------------------------|--------|
| Duration | 73.4s | 347.7s |
| Cost | $0.2424 | $0.0000 |
| Test coverage | 0.0% | 0.0% |
| Cyclomatic complexity | 1455.0 | 3437.0 |
| Coupling score | 10.0 | 10.0 |
| Duplication % | 59.9% | 23.7% |
| Friction items found | 4 | 0 |
| Friction items resolved | 0 | 0 |
| Design revisions | 0 | 1 |

## Studio wins
- duplication
- design_feedback_loop

## Baseline wins
- complexity

## Errors

Baseline: none
Studio: (sqlalchemy.dialects.postgresql.asyncpg.Error) <class 'asyncpg.exceptions.NumericValueOutOfRangeError'>: numeric field overflow
DETAIL:  A field with precision 5, scale 2 must round to an absolute value less than 10^3.
[SQL: UPDATE slices SET status=$1::VARCHAR, test_coverage=$2::NUMERIC(5, 2), cyclomatic_complexity=$3::NUMERIC(5, 2), coupling_score=$4::NUMERIC(5, 2), duplication_pct=$5::NUMERIC(5, 2) WHERE slices.id = $6::UUID]
[parameters: ('done', 0.0, 3437.0, 10.0, 23.72057513678585, UUID('3e0d8d66-2ea7-43c2-b159-91f97128afb7'))]
(Background on this error at: https://sqlalche.me/e/20/dbapi)
