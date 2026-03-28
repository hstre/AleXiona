import os
import json
import threading
import uuid
import re
from datetime import datetime, timezone
from neo4j import GraphDatabase
from models import Claim, GraphData


# ── Per-session claim cache ────────────────────────────────────────────────────

class _SessionCache:
    """Thread-safe in-memory cache for per-session claim lists.

    Caches the result of get_all_claims_for_session keyed by session_id.
    Every write path that mutates claims must call invalidate() so readers
    never see stale data.
    """

    def __init__(self) -> None:
        self._lock   = threading.Lock()
        self._store: dict[str, list[dict]] = {}

    def get(self, session_id: str) -> list[dict] | None:
        with self._lock:
            return self._store.get(session_id)

    def set(self, session_id: str, claims: list[dict]) -> None:
        with self._lock:
            self._store[session_id] = claims

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            self._store.pop(session_id, None)

    def invalidate_all(self) -> None:
        with self._lock:
            self._store.clear()


def _safe_json(raw: str | None, default):
    """Parse JSON string, returning default on any error."""
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default


def _deserialize_audit_row(node: dict) -> dict:
    """Convert a raw Neo4j AuditEvent node to a plain Python dict."""
    return {
        "id":             node.get("id", ""),
        "event_type":     node.get("event_type", ""),
        "claim_id":       node.get("claim_id", ""),
        "session_id":     node.get("session_id", ""),
        "actor":          node.get("actor", ""),
        "pipeline_stage": node.get("pipeline_stage", ""),
        "timestamp":      node.get("timestamp", ""),
        "before":         _safe_json(node.get("before"), None),
        "after":          _safe_json(node.get("after"),  None),
        "meta":           _safe_json(node.get("meta"),   {}),
    }

# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: "Neo4jClient | None" = None


def get_db() -> "Neo4jClient":
    global _instance
    if _instance is None:
        _instance = Neo4jClient()
    return _instance


# ── Key-term helper (mirrors conflict_engine, avoids circular import) ─────────

_KEY_TERM_RE = re.compile(r'\b[a-zA-ZäöüÄÖÜß]{4,}\b')


def _key_terms(text: str) -> set[str]:
    return set(_KEY_TERM_RE.findall(text.lower()))


# ── Client ────────────────────────────────────────────────────────────────────

class Neo4jClient:
    def __init__(self):
        uri      = os.getenv("NEO4J_URI",  "bolt://localhost:7687")
        user     = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD")
        if not password:
            raise RuntimeError(
                "NEO4J_PASSWORD environment variable is required but not set."
            )
        self._cache = _SessionCache()
        def _env_int(key: str, default: int) -> int:
            try:
                return int(os.getenv(key, str(default)))
            except (ValueError, TypeError):
                return default

        def _env_float(key: str, default: float) -> float:
            try:
                return float(os.getenv(key, str(default)))
            except (ValueError, TypeError):
                return default

        self.driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            # How many connections the pool may open simultaneously.
            max_connection_pool_size=_env_int("NEO4J_POOL_SIZE", 20),
            # Seconds to wait for a free connection before raising.
            connection_acquire_timeout=_env_float("NEO4J_ACQUIRE_TIMEOUT", 30.0),
            # Retire a connection after this many seconds (avoids stale TCP).
            max_connection_lifetime=_env_int("NEO4J_MAX_CONN_LIFETIME", 1800),
        )
        self._init_schema()

    def _init_schema(self):
        with self.driver.session() as s:
            s.run("CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE")
            s.run("CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")
            s.run("CREATE INDEX claim_session IF NOT EXISTS FOR (c:Claim) ON (c.session_id)")
            s.run("CREATE CONSTRAINT audit_event_id IF NOT EXISTS FOR (a:AuditEvent) REQUIRE a.id IS UNIQUE")
            s.run("CREATE INDEX audit_claim IF NOT EXISTS FOR (a:AuditEvent) ON (a.claim_id)")
            s.run("CREATE INDEX audit_session IF NOT EXISTS FOR (a:AuditEvent) ON (a.session_id)")
            s.run("CREATE CONSTRAINT snapshot_id IF NOT EXISTS FOR (sn:OrchestratorSnapshot) REQUIRE sn.id IS UNIQUE")
            s.run("CREATE INDEX snapshot_session IF NOT EXISTS FOR (sn:OrchestratorSnapshot) ON (sn.session_id)")

    def close(self):
        self.driver.close()

    # ── Write ────────────────────────────────────────────────────────────────

    def store_claims(self, claims: list[Claim], session_id: str) -> list[str]:
        claim_ids = []
        with self.driver.session() as s, s.begin_transaction() as tx:
            for claim in claims:
                cid = str(uuid.uuid4())
                claim_ids.append(cid)
                now = datetime.now(timezone.utc).isoformat()

                # Resolve optional datetime fields to ISO strings
                event_time_iso = (
                    claim.event_time.isoformat() if claim.event_time else None
                )
                assertion_time_iso = (
                    claim.assertion_time.isoformat()
                    if claim.assertion_time
                    else now
                )

                tx.run(
                    """
                    CREATE (c:Claim {
                        id: $id, text: $text, session_id: $session_id,
                        evidence_support_score: $ess, claim_type: $ct,
                        source_type: $st, source_ref: $sr,
                        derived_from: $df, related_to: $rt,
                        status: $status,
                        time_offset: $to, trend: $trend,
                        created_at: $now,
                        evidence_tier: $evidence_tier,
                        negated: $negated,
                        uncertainty_flag: $uncertainty_flag,
                        normalized_token: $normalized_token,
                        patient_data_ref: $patient_data_ref,
                        event_time: $event_time,
                        assertion_time: $assertion_time,
                        supersedes_claim_id: $supersedes_claim_id,
                        projection_confidence: $projection_confidence,
                        projection_method: $projection_method,
                        spl_unit_id: $spl_unit_id,
                        spl_projection_id: $spl_projection_id,
                        spl_emission_rule: $spl_emission_rule,
                        spl_h_norm: $spl_h_norm
                    })
                    """,
                    id=cid, text=claim.text, session_id=session_id,
                    ess=claim.evidence_support_score,
                    ct=claim.claim_type.value,
                    st=claim.source_type.value,
                    sr=claim.source_ref,
                    df=json.dumps(claim.derived_from),
                    rt=json.dumps(claim.related_to),
                    status=claim.status.value,
                    to=claim.time_offset,
                    trend=claim.trend.value,
                    now=now,
                    evidence_tier=claim.evidence_tier,
                    negated=claim.negated,
                    uncertainty_flag=claim.uncertainty_flag,
                    normalized_token=claim.normalized_token,
                    patient_data_ref=claim.patient_data_ref,
                    event_time=event_time_iso,
                    assertion_time=assertion_time_iso,
                    supersedes_claim_id=claim.supersedes_claim_id,
                    projection_confidence=claim.projection_confidence,
                    projection_method=claim.projection_method,
                    spl_unit_id=claim.spl_unit_id,
                    spl_projection_id=claim.spl_projection_id,
                    spl_emission_rule=claim.spl_emission_rule,
                    spl_h_norm=claim.spl_h_norm,
                )

                for entity_name in claim.entities:
                    tx.run(
                        """
                        MERGE (e:Entity {name: $name})
                        WITH e
                        MATCH (c:Claim {id: $cid})
                        MERGE (c)-[:MENTIONS]->(e)
                        """,
                        name=entity_name, cid=cid,
                    )

                for rel in claim.relations:
                    tx.run(
                        """
                        MERGE (f:Entity {name: $from_name})
                        MERGE (t:Entity {name: $to_name})
                        MERGE (f)-[r:RELATION {type: $rel_type}]->(t)
                        """,
                        from_name=rel.from_entity,
                        to_name=rel.to_entity,
                        rel_type=rel.type,
                    )

        # Invalidate AFTER the transaction commits so concurrent reads don't
        # fetch stale data that predates the write.
        self._cache.invalidate(session_id)
        return claim_ids

    def link_possible_related(self, new_claim_ids: list[str], session_id: str) -> None:
        """Heuristic: create POSSIBLE_RELATED edges and populate `related_to` on new claims
        for existing session claims with >= 2 shared key terms.

        This is NOT the same as epistemic derivation (`derived_from`).
        Edges are labelled POSSIBLE_RELATED; `related_to` on the claim node is also updated.
        """
        if not new_claim_ids:
            return
        with self.driver.session() as s:
            # Fetch new and old claims in two separate queries to avoid Python-side
            # filtering (eliminates TOCTOU skew when claims are created concurrently).
            new_claims = s.run(
                "MATCH (c:Claim {session_id: $sid}) WHERE c.id IN $ids "
                "RETURN c.id AS id, c.text AS text",
                sid=session_id, ids=new_claim_ids,
            ).data()
            old_claims = s.run(
                "MATCH (c:Claim {session_id: $sid}) WHERE NOT c.id IN $ids "
                "RETURN c.id AS id, c.text AS text",
                sid=session_id, ids=new_claim_ids,
            ).data()
            if not old_claims:
                return
            for nc in new_claims:
                nc_terms = _key_terms(nc["text"])
                sources = [
                    oc["id"] for oc in old_claims
                    if len(nc_terms & _key_terms(oc["text"])) >= 2
                ]
                if not sources:
                    continue
                # Update related_to on the claim node (JSON list)
                s.run(
                    "MATCH (c:Claim {id: $id}) SET c.related_to = $rt",
                    id=nc["id"], rt=json.dumps(sources),
                )
                # Batch-create POSSIBLE_RELATED edges with UNWIND (avoids N+1 queries)
                s.run(
                    """
                    MATCH (nc:Claim {id: $nc_id})
                    UNWIND $src_ids AS src_id
                    MATCH (oc:Claim {id: src_id})
                    MERGE (nc)-[:POSSIBLE_RELATED]->(oc)
                    """,
                    nc_id=nc["id"], src_ids=sources,
                )

    def link_explicit_derived_from(self, new_claim_id: str, source_ids: list[str]) -> None:
        """Create explicit DERIVES_FROM edges from a new claim to each listed source claim.
        These are set by the user, not inferred — they carry epistemic weight.
        """
        with self.driver.session() as s:
            for src_id in source_ids:
                s.run(
                    """
                    MATCH (nc:Claim {id: $nc_id})
                    MATCH (oc:Claim {id: $oc_id})
                    MERGE (nc)-[:DERIVES_FROM]->(oc)
                    """,
                    nc_id=new_claim_id, oc_id=src_id,
                )

    # Fields that callers are allowed to update via update_claim().
    # This prevents arbitrary Cypher clause injection through field names.
    _ALLOWED_UPDATE_FIELDS: frozenset = frozenset({
        "text", "evidence_support_score", "claim_type", "source_type",
        "status", "trend", "time_offset", "source_ref", "notes",
        "negated", "uncertainty_flag", "supersedes_claim_id", "valid_until",
        "evidence_tier",
    })

    def update_claim(self, claim_id: str, fields: dict, *, session_id: str | None = None) -> None:
        """Update allowed non-None fields on a Claim node."""
        clean = {
            k: (v.value if hasattr(v, "value") else v)
            for k, v in fields.items()
            if v is not None and k in self._ALLOWED_UPDATE_FIELDS
        }
        if not clean:
            return
        set_clause = ", ".join(f"c.{k} = ${k}" for k in clean)
        with self.driver.session() as s:
            s.run(f"MATCH (c:Claim {{id: $id}}) SET {set_clause}", id=claim_id, **clean)
        if session_id:
            self._cache.invalidate(session_id)

    def delete_claim(self, claim_id: str, *, session_id: str | None = None) -> None:
        with self.driver.session() as s:
            s.run("MATCH (c:Claim {id: $id}) DETACH DELETE c", id=claim_id)
        if session_id:
            self._cache.invalidate(session_id)

    # ── Audit ─────────────────────────────────────────────────────────────────

    def store_audit_event(self, event: "AuditEvent") -> None:  # type: ignore[name-defined]
        """Persist an AuditEvent node and link it to its Claim (if it exists)."""
        from models import AuditEvent as _AuditEvent  # avoid circular at module level
        with self.driver.session() as s:
            s.run(
                """
                CREATE (a:AuditEvent {
                    id: $id, event_type: $event_type,
                    claim_id: $claim_id, session_id: $session_id,
                    actor: $actor, pipeline_stage: $pipeline_stage,
                    timestamp: $timestamp,
                    before: $before, after: $after,
                    meta: $meta
                })
                WITH a
                OPTIONAL MATCH (c:Claim {id: $claim_id})
                FOREACH (_ IN CASE WHEN c IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (a)-[:AUDITS]->(c)
                )
                """,
                id=event.id,
                event_type=event.event_type.value,
                claim_id=event.claim_id,
                session_id=event.session_id,
                actor=event.actor,
                pipeline_stage=event.pipeline_stage,
                timestamp=event.timestamp.isoformat(),
                before=json.dumps(event.before, default=str) if event.before is not None else None,
                after=json.dumps(event.after, default=str) if event.after is not None else None,
                meta=json.dumps(event.meta, default=str),
            )

    def get_claim_audit_trail(self, claim_id: str) -> list[dict]:
        """Return all AuditEvents for a single Claim, oldest first."""
        with self.driver.session() as s:
            result = s.run(
                """
                MATCH (a:AuditEvent {claim_id: $claim_id})
                RETURN a ORDER BY a.timestamp ASC
                """,
                claim_id=claim_id,
            )
            return [_deserialize_audit_row(r["a"]) for r in result]

    def get_session_audit_trail(self, session_id: str) -> list[dict]:
        """Return all AuditEvents for a session, oldest first."""
        with self.driver.session() as s:
            result = s.run(
                """
                MATCH (a:AuditEvent {session_id: $session_id})
                RETURN a ORDER BY a.timestamp ASC
                """,
                session_id=session_id,
            )
            return [_deserialize_audit_row(r["a"]) for r in result]

    # ── Orchestrator Snapshots ────────────────────────────────────────────────

    def store_orchestrator_snapshot(self, snapshot: "OrchestratorSnapshot") -> None:  # type: ignore[name-defined]
        """Persist an OrchestratorSnapshot node for this session."""
        import json as _json
        props = {
            "id":                 snapshot.id,
            "session_id":         snapshot.session_id,
            "recorded_at":        snapshot.recorded_at,
            "trigger":            snapshot.trigger,
            "trigger_claim_ids":  _json.dumps(snapshot.trigger_claim_ids),
            "leading_hypothesis": snapshot.leading_hypothesis,
            "orchestrated_score": snapshot.orchestrated_score,
            "status":             snapshot.status,
            "why":                snapshot.why,
            "key_conflicts":      _json.dumps(snapshot.key_conflicts),
            "missing_critical":   _json.dumps(snapshot.missing_critical),
            "next_action":        snapshot.next_action,
            "score_breakdown":    _json.dumps(snapshot.score_breakdown.model_dump()),
            "alternatives":       _json.dumps([a.model_dump() for a in snapshot.alternatives]),
            "state_transition":   snapshot.state_transition,
            "decision_allowed":   snapshot.decision_allowed,
            "generated_at":       snapshot.generated_at,
        }
        with self.driver.session() as s:
            s.run(
                """
                CREATE (sn:OrchestratorSnapshot $props)
                """,
                props=props,
            )

    def get_orchestrator_snapshots(self, session_id: str) -> list[dict]:
        """Return all OrchestratorSnapshots for a session, oldest first."""
        import json as _json
        with self.driver.session() as s:
            result = s.run(
                """
                MATCH (sn:OrchestratorSnapshot {session_id: $session_id})
                RETURN sn ORDER BY sn.recorded_at ASC
                """,
                session_id=session_id,
            )
            rows = []
            for r in result:
                d = dict(r["sn"])
                for field in ("trigger_claim_ids", "key_conflicts", "missing_critical",
                              "score_breakdown", "alternatives"):
                    if isinstance(d.get(field), str):
                        try:
                            d[field] = _json.loads(d[field])
                        except Exception:
                            pass
                rows.append(d)
            return rows

    def get_claim_by_id(self, claim_id: str) -> dict | None:
        """Return a single Claim's properties as a dict, or None if not found."""
        with self.driver.session() as s:
            result = s.run(
                "MATCH (c:Claim {id: $id}) RETURN c LIMIT 1",
                id=claim_id,
            )
            row = result.single()
            if row is None:
                return None
            return dict(row["c"])

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_all_claims_for_session(self, session_id: str) -> list[dict]:
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached

        with self.driver.session() as s:
            result = s.run(
                """
                MATCH (c:Claim {session_id: $session_id})
                RETURN c.id AS id, c.text AS text,
                       c.evidence_support_score AS ess,
                       c.claim_type AS claim_type,
                       c.source_type AS source_type,
                       c.source_ref AS source_ref,
                       c.derived_from AS derived_from,
                       c.related_to AS related_to,
                       c.status AS status,
                       c.time_offset AS time_offset,
                       c.trend AS trend,
                       c.created_at AS created_at,
                       c.notes AS notes,
                       c.negated AS negated,
                       c.valid_until AS valid_until
                ORDER BY c.created_at
                """,
                session_id=session_id,
            )
            claims = [
                {
                    "id":                     r["id"],
                    "text":                   r["text"],
                    "evidence_support_score": r["ess"] if r["ess"] is not None else 0.8,
                    "claim_type":             r["claim_type"] or "finding",
                    "source_type":            r["source_type"] or "llm",
                    "source_ref":             r["source_ref"] or "",
                    "derived_from":           _safe_json(r["derived_from"], []),
                    "related_to":             _safe_json(r["related_to"], []),
                    "status":                 r["status"] or "active",
                    "time_offset":            r["time_offset"],
                    "trend":                  r["trend"] or "unknown",
                    "created_at":             r["created_at"] or "",
                    "notes":                  r["notes"] or "",
                    "negated":                bool(r.get("negated") or False),
                    "valid_until":            r.get("valid_until"),
                }
                for r in result
            ]
        self._cache.set(session_id, claims)
        return claims

    def get_graph(self, session_id: str) -> GraphData:
        nodes: dict = {}
        edges: dict = {}

        with self.driver.session() as s:
            # Claims + their entities
            result = s.run(
                """
                MATCH (c:Claim {session_id: $session_id})
                OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
                RETURN c, collect(e) AS entities
                """,
                session_id=session_id,
            )
            for record in result:
                c = record["c"]
                if c.element_id not in nodes:
                    nodes[c.element_id] = {
                        "id":                     c.element_id,
                        "label":                  c["text"][:55] + ("…" if len(c["text"]) > 55 else ""),
                        "fullText":               c["text"],
                        "type":                   "Claim",
                        "claimId":                c["id"],
                        "evidence_support_score": c.get("evidence_support_score", 0.8),
                        "claim_type":             c.get("claim_type", "finding"),
                        "source_type":            c.get("source_type", "llm"),
                        "source_ref":             c.get("source_ref", ""),
                        "status":                 c.get("status", "active"),
                        "time_offset":            c.get("time_offset"),
                        "trend":                  c.get("trend", "unknown"),
                        "created_at":             c.get("created_at", ""),
                        "derived_from":           _safe_json(c.get("derived_from"), []),
                        "related_to":             _safe_json(c.get("related_to"), []),
                        "notes":                  c.get("notes", ""),
                    }

                for e in record["entities"]:
                    if e is None:
                        continue
                    if e.element_id not in nodes:
                        nodes[e.element_id] = {
                            "id":    e.element_id,
                            "label": e["name"],
                            "type":  "Entity",
                        }
                    eid = f"m-{c.element_id}-{e.element_id}"
                    if eid not in edges:
                        edges[eid] = {
                            "id": eid, "source": c.element_id,
                            "target": e.element_id, "label": "mentions",
                        }

            # Entity-to-entity relations
            result2 = s.run(
                """
                MATCH (c:Claim {session_id: $session_id})-[:MENTIONS]->(e1:Entity)
                MATCH (e1)-[r:RELATION]->(e2:Entity)
                RETURN DISTINCT e1, r, e2
                """,
                session_id=session_id,
            )
            for record in result2:
                e1, r, e2 = record["e1"], record["r"], record["e2"]
                for e in (e1, e2):
                    if e.element_id not in nodes:
                        nodes[e.element_id] = {
                            "id": e.element_id, "label": e["name"], "type": "Entity",
                        }
                if r.element_id not in edges:
                    edges[r.element_id] = {
                        "id": r.element_id,
                        "source": e1.element_id, "target": e2.element_id,
                        "label": r["type"],
                    }

            # DERIVES_FROM (legacy) and POSSIBLE_RELATED edges between Claims
            result3 = s.run(
                """
                MATCH (c1:Claim {session_id: $session_id})-[r:DERIVES_FROM|POSSIBLE_RELATED]->(c2:Claim {session_id: $session_id})
                RETURN c1.id AS c1_id, c2.id AS c2_id, type(r) AS rel_type
                """,
                session_id=session_id,
            )
            for record in result3:
                src_elem = next(
                    (k for k, v in nodes.items()
                     if v.get("type") == "Claim" and v.get("claimId") == record["c1_id"]),
                    None,
                )
                tgt_elem = next(
                    (k for k, v in nodes.items()
                     if v.get("type") == "Claim" and v.get("claimId") == record["c2_id"]),
                    None,
                )
                if src_elem and tgt_elem:
                    label = "possible_related" if record["rel_type"] == "POSSIBLE_RELATED" else "derives_from"
                    eid = f"{label}-{record['c1_id']}-{record['c2_id']}"
                    if eid not in edges:
                        edges[eid] = {
                            "id": eid,
                            "source": src_elem, "target": tgt_elem,
                            "label": label,
                        }

        return GraphData(nodes=list(nodes.values()), edges=list(edges.values()))

    def get_context_for_query(self, session_id: str) -> str:
        claims = self.get_all_claims_for_session(session_id)
        if not claims:
            return ""
        return "\n".join(
            f"- [{c['claim_type'].upper()}] {c['text']} (support: {int(c['evidence_support_score']*100)}%)"
            for c in claims
        )

    # ── Entity deduplication ─────────────────────────────────────────────────

    def get_entity_groups(self, session_id: str) -> list[dict]:
        """Return groups of Entity names that normalise to the same key (case-insensitive strip).
        Only groups with ≥2 members are returned.
        """
        with self.driver.session() as s:
            rows = s.run(
                """
                MATCH (e:Entity)<-[:MENTIONS]-(c:Claim {session_id: $sid})
                RETURN DISTINCT e.name AS name
                ORDER BY name
                """,
                sid=session_id,
            ).data()

        # Group by normalised key
        groups: dict[str, list[str]] = {}
        for row in rows:
            key = row["name"].strip().lower()
            groups.setdefault(key, []).append(row["name"])

        return [
            {"canonical": members[0], "aliases": members[1:], "key": key}
            for key, members in groups.items()
            if len(members) >= 2
        ]

    def merge_entities(self, session_id: str, canonical_name: str, alias_names: list[str]) -> int:
        """Redirect all MENTIONS/RELATION edges from each alias to the canonical entity,
        then delete the alias nodes. Returns the count of aliases merged.
        """
        merged = 0
        with self.driver.session() as s:
            for alias in alias_names:
                if alias == canonical_name:
                    continue
                # Repoint MENTIONS edges from alias to canonical
                s.run(
                    """
                    MATCH (c:Claim)-[:MENTIONS]->(alias:Entity {name: $alias})
                    MATCH (canonical:Entity {name: $canonical})
                    MERGE (c)-[:MENTIONS]->(canonical)
                    """,
                    alias=alias, canonical=canonical_name,
                )
                # Repoint outgoing RELATION edges
                s.run(
                    """
                    MATCH (alias:Entity {name: $alias})-[r:RELATION]->(other:Entity)
                    MATCH (canonical:Entity {name: $canonical})
                    MERGE (canonical)-[:RELATION {type: r.type}]->(other)
                    """,
                    alias=alias, canonical=canonical_name,
                )
                # Repoint incoming RELATION edges
                s.run(
                    """
                    MATCH (other:Entity)-[r:RELATION]->(alias:Entity {name: $alias})
                    MATCH (canonical:Entity {name: $canonical})
                    MERGE (other)-[:RELATION {type: r.type}]->(canonical)
                    """,
                    alias=alias, canonical=canonical_name,
                )
                # Delete alias
                s.run("MATCH (e:Entity {name: $name}) DETACH DELETE e", name=alias)
                merged += 1
        # Only invalidate the affected session's cache — not all sessions.
        self._cache.invalidate(session_id)
        return merged

    # ── Session export / import ───────────────────────────────────────────────

    def export_session(self, session_id: str) -> dict:
        """Return a full serialisable snapshot of all claims for the session."""
        claims = self.get_all_claims_for_session(session_id)
        return {
            "version":     "1",
            "session_id":  session_id,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "claims":      claims,
        }

    def import_session(self, session_id: str, claims_data: list[dict]) -> dict:
        """Re-create claims from a snapshot export.
        Old IDs are remapped to new UUIDs; derived_from edges are re-created.
        Returns a summary with old→new id mapping.
        """
        from models import Claim, ClaimType, SourceType, ClaimStatus, ClaimTrend, Relation

        id_map: dict[str, str] = {}

        # Pass 1: create all claim nodes
        for c in claims_data:
            try:
                claim = Claim(
                    text=c["text"],
                    entities=c.get("entities", []),
                    relations=[Relation(**r) for r in c.get("relations", [])],
                    evidence_support_score=max(0.0, min(1.0, float(c.get("evidence_support_score", 0.8)))),
                    claim_type=ClaimType(c.get("claim_type", "finding")),
                    source_type=SourceType(c.get("source_type", "clinician")),
                    source_ref=c.get("source_ref", ""),
                    status=ClaimStatus(c.get("status", "active")),
                    time_offset=c.get("time_offset"),
                    trend=ClaimTrend(c.get("trend", "unknown")),
                )
            except Exception:
                continue  # skip malformed records
            new_ids = self.store_claims([claim], session_id)
            id_map[c["id"]] = new_ids[0]

        # Pass 2: re-create explicit DERIVES_FROM edges
        for c in claims_data:
            old_derived = c.get("derived_from", [])
            if not old_derived or c["id"] not in id_map:
                continue
            mapped = [id_map[old] for old in old_derived if old in id_map]
            if mapped:
                self.link_explicit_derived_from(id_map[c["id"]], mapped)

        self._cache.invalidate(session_id)
        return {"imported": len(id_map), "skipped": len(claims_data) - len(id_map)}

    def list_sessions(self) -> list[dict]:
        with self.driver.session() as s:
            result = s.run(
                """
                MATCH (c:Claim)
                RETURN c.session_id AS session_id, count(c) AS claim_count
                ORDER BY claim_count DESC
                """
            )
            return [{"session_id": r["session_id"], "claim_count": r["claim_count"]} for r in result]

    def delete_session(self, session_id: str):
        self._cache.invalidate(session_id)
        with self.driver.session() as s:
            s.run("MATCH (c:Claim {session_id: $session_id}) DETACH DELETE c", session_id=session_id)
            s.run("MATCH (a:AuditEvent {session_id: $session_id}) DETACH DELETE a", session_id=session_id)
