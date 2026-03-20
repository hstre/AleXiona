import os
import json
import uuid
import re
from datetime import datetime, timezone
from neo4j import GraphDatabase
from models import Claim, GraphData

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
        uri      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
        user     = os.getenv("NEO4J_USER",     "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "alexiona123")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._init_schema()

    def _init_schema(self):
        with self.driver.session() as s:
            s.run("CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE")
            s.run("CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")
            s.run("CREATE INDEX claim_session IF NOT EXISTS FOR (c:Claim) ON (c.session_id)")

    def close(self):
        self.driver.close()

    # ── Write ────────────────────────────────────────────────────────────────

    def store_claims(self, claims: list[Claim], session_id: str) -> list[str]:
        claim_ids = []
        with self.driver.session() as s:
            for claim in claims:
                cid = str(uuid.uuid4())
                claim_ids.append(cid)
                now = datetime.now(timezone.utc).isoformat()

                s.run(
                    """
                    CREATE (c:Claim {
                        id: $id, text: $text, session_id: $session_id,
                        evidence_support_score: $ess, claim_type: $ct,
                        source_type: $st, source_ref: $sr,
                        derived_from: $df, status: $status,
                        time_offset: $to, trend: $trend,
                        created_at: $now
                    })
                    """,
                    id=cid, text=claim.text, session_id=session_id,
                    ess=claim.evidence_support_score,
                    ct=claim.claim_type.value,
                    st=claim.source_type.value,
                    sr=claim.source_ref,
                    df=json.dumps(claim.derived_from),
                    status=claim.status.value,
                    to=claim.time_offset,
                    trend=claim.trend.value,
                    now=now,
                )

                for entity_name in claim.entities:
                    s.run(
                        """
                        MERGE (e:Entity {name: $name})
                        WITH e
                        MATCH (c:Claim {id: $cid})
                        MERGE (c)-[:MENTIONS]->(e)
                        """,
                        name=entity_name, cid=cid,
                    )

                for rel in claim.relations:
                    s.run(
                        """
                        MERGE (f:Entity {name: $from_name})
                        MERGE (t:Entity {name: $to_name})
                        MERGE (f)-[r:RELATION {type: $rel_type}]->(t)
                        """,
                        from_name=rel.from_entity,
                        to_name=rel.to_entity,
                        rel_type=rel.type,
                    )

        return claim_ids

    def link_possible_related(self, new_claim_ids: list[str], session_id: str) -> None:
        """Heuristic: create POSSIBLE_RELATED edges to existing session claims with >= 2 shared key terms.
        This is NOT the same as epistemic derivation. Edges are labelled `possible_related`
        and must be reviewed before treating them as actual clinical reasoning chains.
        """
        if not new_claim_ids:
            return
        new_id_set = set(new_claim_ids)
        with self.driver.session() as s:
            rows = s.run(
                "MATCH (c:Claim {session_id: $sid}) RETURN c.id AS id, c.text AS text",
                sid=session_id,
            ).data()
            new_claims = [r for r in rows if r["id"] in new_id_set]
            old_claims = [r for r in rows if r["id"] not in new_id_set]
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
                for src_id in sources:
                    s.run(
                        """
                        MATCH (nc:Claim {id: $nc_id})
                        MATCH (oc:Claim {id: $oc_id})
                        MERGE (nc)-[:POSSIBLE_RELATED]->(oc)
                        """,
                        nc_id=nc["id"], oc_id=src_id,
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

    def update_claim(self, claim_id: str, fields: dict) -> None:
        """Update any non-None fields on a Claim node."""
        # Convert enum values to strings for Neo4j
        clean = {k: (v.value if hasattr(v, 'value') else v) for k, v in fields.items() if v is not None}
        if not clean:
            return
        set_clause = ", ".join(f"c.{k} = ${k}" for k in clean)
        with self.driver.session() as s:
            s.run(f"MATCH (c:Claim {{id: $id}}) SET {set_clause}", id=claim_id, **clean)

    def delete_claim(self, claim_id: str):
        with self.driver.session() as s:
            s.run("MATCH (c:Claim {id: $id}) DETACH DELETE c", id=claim_id)

    # ── Read ─────────────────────────────────────────────────────────────────

    def get_all_claims_for_session(self, session_id: str) -> list[dict]:
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
                       c.status AS status,
                       c.time_offset AS time_offset,
                       c.trend AS trend,
                       c.created_at AS created_at
                ORDER BY c.created_at
                """,
                session_id=session_id,
            )
            return [
                {
                    "id":                     r["id"],
                    "text":                   r["text"],
                    "evidence_support_score": r["ess"] or 0.8,
                    "claim_type":             r["claim_type"] or "finding",
                    "source_type":            r["source_type"] or "llm",
                    "source_ref":             r["source_ref"] or "",
                    "derived_from":           json.loads(r["derived_from"] or "[]"),
                    "status":                 r["status"] or "active",
                    "time_offset":            r["time_offset"],
                    "trend":                  r["trend"] or "unknown",
                    "created_at":             r["created_at"] or "",
                }
                for r in result
            ]

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
                        "derived_from":           json.loads(c.get("derived_from") or "[]"),
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

    def merge_entities(self, canonical_name: str, alias_names: list[str]) -> int:
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
        with self.driver.session() as s:
            s.run("MATCH (c:Claim {session_id: $session_id}) DETACH DELETE c", session_id=session_id)
