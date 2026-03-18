import os
import uuid
from neo4j import GraphDatabase
from models import Claim, GraphData


class Neo4jClient:
    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "alexiona123")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self._init_constraints()

    def _init_constraints(self):
        with self.driver.session() as session:
            session.run("CREATE CONSTRAINT claim_id IF NOT EXISTS FOR (c:Claim) REQUIRE c.id IS UNIQUE")
            session.run("CREATE CONSTRAINT entity_name IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE")

    def close(self):
        self.driver.close()

    def store_claims(self, claims: list[Claim], session_id: str) -> list[str]:
        claim_ids = []
        with self.driver.session() as session:
            for claim in claims:
                claim_id = str(uuid.uuid4())
                claim_ids.append(claim_id)

                session.run(
                    "CREATE (c:Claim {id: $id, text: $text, session_id: $session_id})",
                    id=claim_id, text=claim.text, session_id=session_id,
                )

                for entity_name in claim.entities:
                    session.run(
                        """
                        MERGE (e:Entity {name: $name})
                        WITH e
                        MATCH (c:Claim {id: $claim_id})
                        MERGE (c)-[:MENTIONS]->(e)
                        """,
                        name=entity_name, claim_id=claim_id,
                    )

                for rel in claim.relations:
                    session.run(
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

    def get_graph(self, session_id: str) -> GraphData:
        nodes: dict = {}
        edges: dict = {}

        with self.driver.session() as session:
            # Query 1: claims + their mentioned entities
            result = session.run(
                """
                MATCH (c:Claim {session_id: $session_id})
                OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
                RETURN c, collect(e) AS entities
                """,
                session_id=session_id,
            )

            claim_node_ids: set[str] = set()

            for record in result:
                c = record["c"]
                if c.element_id not in nodes:
                    nodes[c.element_id] = {
                        "id": c.element_id,
                        "label": c["text"][:60] + ("..." if len(c["text"]) > 60 else ""),
                        "fullText": c["text"],
                        "type": "Claim",
                        "claimId": c["id"],
                    }
                    claim_node_ids.add(c.element_id)

                for e in record["entities"]:
                    if e is None:
                        continue
                    if e.element_id not in nodes:
                        nodes[e.element_id] = {
                            "id": e.element_id,
                            "label": e["name"],
                            "type": "Entity",
                        }
                    edge_id = f"m-{c.element_id}-{e.element_id}"
                    if edge_id not in edges:
                        edges[edge_id] = {
                            "id": edge_id,
                            "source": c.element_id,
                            "target": e.element_id,
                            "label": "mentions",
                        }

            # Query 2: entity-to-entity relations for entities in this session
            result2 = session.run(
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
                            "id": e.element_id,
                            "label": e["name"],
                            "type": "Entity",
                        }

                edge_id = r.element_id
                if edge_id not in edges:
                    edges[edge_id] = {
                        "id": edge_id,
                        "source": e1.element_id,
                        "target": e2.element_id,
                        "label": r["type"],
                    }

        return GraphData(nodes=list(nodes.values()), edges=list(edges.values()))

    def get_all_claims_for_session(self, session_id: str) -> list[dict]:
        with self.driver.session() as session:
            result = session.run(
                "MATCH (c:Claim {session_id: $session_id}) RETURN c.id AS id, c.text AS text",
                session_id=session_id,
            )
            return [{"id": r["id"], "text": r["text"]} for r in result]

    def list_sessions(self) -> list[dict]:
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Claim)
                RETURN c.session_id AS session_id, count(c) AS claim_count
                ORDER BY claim_count DESC
                """
            )
            return [{"session_id": r["session_id"], "claim_count": r["claim_count"]} for r in result]

    def delete_session(self, session_id: str):
        with self.driver.session() as session:
            # Remove claims; orphaned entities are left (they may be shared)
            session.run(
                "MATCH (c:Claim {session_id: $session_id}) DETACH DELETE c",
                session_id=session_id,
            )

    def update_claim(self, claim_id: str, new_text: str):
        with self.driver.session() as session:
            session.run(
                "MATCH (c:Claim {id: $id}) SET c.text = $text",
                id=claim_id, text=new_text,
            )

    def delete_claim(self, claim_id: str):
        with self.driver.session() as session:
            session.run(
                "MATCH (c:Claim {id: $id}) DETACH DELETE c",
                id=claim_id,
            )

    def get_context_for_query(self, session_id: str, query: str) -> str:
        claims = self.get_all_claims_for_session(session_id)
        if not claims:
            return ""
        return "\n".join(f"- {c['text']}" for c in claims)
