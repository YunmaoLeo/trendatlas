# Agent usage contract

This project is a deterministic, book-grounded stock chart tool. To answer a user request about a ticker:

1. Run `.venv/bin/python -m stocktrend.cli SYMBOL --period 2y --interval 1d` from this directory, or call `GET /api/analyze` on a running local server.
2. Parse the JSON. Always state `source.provider`, `source.as_of`, `last.close`, `trend.direction`, and any `warnings` before treating a pattern as current.
3. Describe patterns using `patterns[].status`, `trigger`, `evidence`, `book_chapters`, and `target_state`. Never promote a `待确认` or `待突破` shape to a confirmed signal. `events[]` contains observational gap/reversal candidates, not a validated four-type gap classification.
4. The `measured_target` is a geometric projection, not a forecast. The `risk.protective_reference` is a reference level, not a guaranteed execution price or personalized order.
5. For method questions, use `KNOWLEDGE.md` and `COVERAGE.md`; distinguish source-book rules from documented engineering thresholds. Do not invent new indicator interpretations as if they came from the book.
6. If the user supplies a hypothetical entry date, pass `--entry-date YYYY-MM-DD`; report `risk.basis_ladder` as an illustrative path with possible stop touches, never as an executed trade. To assess multiple actual long positions, ask for or use an explicitly provided CSV (`symbol,shares,last,stop`) and run `.venv/bin/python -m stocktrend.portfolio --csv PATH --capital AMOUNT`.
7. Never trade or submit an order on the user's behalf from this tool.
8. For historical validation, run `.venv/bin/python -m stocktrend.replay SYMBOL --period 5y --horizon 20` or `GET /api/replay`; read `data_quality`, `complete_count`, `pending_count`, `by_pattern[].small_sample`, and `warnings` before discussing any historical pattern behavior. `directional_return_pct` is a retrospective price move from the signal close, not a tradable return or a validated win rate. See `REPLAY.md`.
