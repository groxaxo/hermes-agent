"""Bounded current-query recall; background completion never publishes recall state."""

from __future__ import annotations

import logging
import math
import threading
import time

from plugins.memory.honcho.client import spawn_context_thread

logger = logging.getLogger("plugins.memory.honcho")


def prefetch_sync(provider, query: str) -> str:
    timeout = provider._config.timeout if provider._config else None
    budget = timeout if timeout is not None and math.isfinite(timeout) and timeout > 0 else 5.0
    deadline = time.monotonic() + budget
    if provider._is_trivial_prompt(query):
        return ""
    # No lock wait can extend the request budget. Keep the slot occupied even after
    # a caller times out, until the actual worker (including any HTTP call) exits.
    if not provider._recall_sync_lock.acquire(blocking=False):
        return ""
    cancelled = threading.Event()
    try:
        worker = provider._recall_sync_thread
        if worker is not None and worker.is_alive():
            return ""
        generation = provider._recall_generation = object()
        session, turn = provider._session_key, provider._turn_count
        if not provider._session_ready():
            provider._start_session_init_background(blocking=False)
            if provider._init_thread is not None:
                provider._init_thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if not provider._session_ready():
                return provider._pop_auth_notice()
        manager = provider._manager
        if (generation is not provider._recall_generation or session != provider._session_key
                or turn != provider._turn_count or time.monotonic() >= deadline):
            return ""

        context_due = (
            not (provider._injection_frequency == "first-turn" and turn > 1)
            and turn - provider._last_context_turn >= provider._context_cadence
        )
        dialectic_due = turn - provider._last_dialectic_turn >= provider._effective_cadence()
        if not context_due and not dialectic_due:
            return ""
        # Resolve all mutable settings before starting the worker. The captured
        # manager/session remain its only I/O owner, even if the provider is reused.
        levels = [provider._resolve_pass_level(i, query=query) for i in range(provider._dialectic_depth)]
        rewriter = provider._query_rewriter if provider._query_rewrite_enabled else None
        holder = {}

        def expired() -> bool:
            return (cancelled.is_set() or generation is not provider._recall_generation
                    or time.monotonic() >= deadline)

        def retrieve() -> None:
            try:
                if expired():
                    return
                base = provider._format_first_turn_context(manager.get_prefetch_context(
                    session, query, current_query_only=True,
                ) or {}) if context_due else ""
                if expired():
                    return

                # Peer representations are eventually derived and can lag a just-written turn.
                # Rewrite the retrieval query with Hermes' configured memory_query_rewrite model
                # (GLM-5.3 on Z.AI here), then retrieve stored evidence directly from Honcho.
                # Honcho dialectic is intentionally not on the synchronous critical path: a backend
                # reasoning outage must never suppress already-persisted memory.
                rewritten = ""
                if rewriter:
                    try:
                        rewritten = rewriter(query).strip()
                    except Exception as exc:
                        logger.debug("Honcho query rewriter failed: %s", exc)
                search_queries = [query]
                if rewritten and rewritten.casefold() != query.casefold():
                    search_queries.insert(0, rewritten)

                evidence_parts = []
                for search_query in search_queries:
                    if expired():
                        return
                    try:
                        hit = manager.search_context(session, search_query, max_tokens=600, peer="user") or ""
                        if hit:
                            evidence_parts.append(f"[Honcho current-query message evidence; query={search_query!r}]\n{hit}")
                    except Exception as exc:
                        logger.debug("Honcho current-query message search failed: %s", exc)

                # Always include a small tail of the current Honcho session. This closes the
                # derivation/index lag gap immediately after a successful per-turn write.
                try:
                    recent = (manager.get_session_context(session, peer="user") or {}).get("recent_messages", [])
                    lines = []
                    for item in recent[-6:]:
                        content = (item.get("content") or "").strip()
                        if content:
                            lines.append(f'[{item.get("role") or "unknown"}] {content[:700]}')
                    if lines:
                        evidence_parts.append("[Honcho recent-session evidence]\n" + "\n".join(lines))
                except Exception as exc:
                    logger.debug("Honcho recent-session recall failed: %s", exc)

                raw_recall = "\n\n".join(dict.fromkeys(evidence_parts))
                dialectic = ""
                holder["result"] = (base, raw_recall, dialectic)
            except Exception as exc:
                logger.debug("Honcho synchronous recall failed: %s", exc)

        worker = spawn_context_thread(retrieve, name="honcho-recall-sync")
        provider._recall_sync_thread = worker
        worker.start()
        worker.join(timeout=max(0.0, deadline - time.monotonic()))
        if (worker.is_alive() or time.monotonic() >= deadline or "result" not in holder
                or generation is not provider._recall_generation
                or provider._manager is not manager or provider._session_key != session
                or provider._turn_count != turn):
            return ""
        base, raw_recall, dialectic = holder["result"]
        if context_due:
            provider._last_context_turn = turn
        if dialectic_due:
            provider._last_dialectic_turn = turn
            if dialectic:
                provider._dialectic_empty_streak = 0
            else:
                provider._dialectic_empty_streak += 1
        parts = [provider._pop_auth_notice(), base, raw_recall, dialectic]
        return provider._truncate_to_budget("\n\n".join(part for part in parts if part and part.strip()))
    finally:
        # Thread.join may return before a coarse host clock crosses the deadline.
        # Record caller abandonment explicitly before a late HTTP call can resume.
        cancelled.set()
        provider._recall_sync_lock.release()
