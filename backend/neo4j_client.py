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
                    """
                    CREATE (c:Claim {id: $id, text: $text, session_id: $session_id})
                    """,
                    id=claim_id, text=claim.text, session_id=session_id
                )

                for entity_name in claim.entities:
                    session.run(
                        """
                        MERGE (e:Entity {name: $name})
                        WITH e
                        MATCH (c:Claim {id: $claim_id})
                        MERGE (c)-[:MENTIONS]->(e)
                        """,
                        name=entity_name, claim_id=claim_id
                    )

                for rel in claim.relations:
                    session.run(
                        """
                        MERGE (from:Entity {name: $from_name})
                        MERGE (to:Entity {name: $to_name})
                        MERGE (from)-[r:RELATION {type: $rel_type}]->(to)
                        """,
                        from_name=rel.from_entity,
                        to_name=rel.to_entity,
                        rel_type=rel.type
                    )

        return claim_ids

    def get_graph(self, session_id: str) -> GraphData:
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (c:Claim {session_id: $session_id})
                OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity)
                OPTIONAL MATCH (e1:Entity)-[r:RELATION]->(e2:Entity)
                WHERE exists((c)-[:MENTIONS]->(e1)) OR exists((c)-[:MENTIONS]->(e2))
                RETURN c, e, e1, r, e2
                """,
                session_id=session_id
            )

            nodes = {}
            edges = {}

            for record in result:
                claim = record["c"]
                if claim and claim.element_id not in nodes:
                    nodes[claim.element_id] = {
                        "id": claim.element_id,
                        "label": claim["text"][:60] + ("..." if len(claim["text"]) > 60 else ""),
                        "fullText": claim["text"],
                        "type": "Claim",
                        "claimId": claim["id"],
                    }

                entity = record["e"]
                if entity and entity.element_id not in nodes:
                    nodes[entity.element_id] = {
                        "id": entity.element_id,
                        "label": entity["name"],
                        "type": "Entity",
                    }

                if entity and claim:
                    edge_id = f"mentions-{claim.element_id}-{entity.element_id}"
                    if edge_id not in edges:
                        edges[edge_id] = {
                            "id": edge_id,
                            "source": claim.element_id,
                            "target": entity.element_id,
                            "label": "mentions",
                        }

                e1 = record["e1"]
                r = record["r"]
                e2 = record["e2"]
                if e1 and r and e2:
                    if e1.element_id not in nodes:
                        nodes[e1.element_id] = {
                            "id": e1.element_id,
                            "label": e1["name"],
                            "type": "Entity",
                        }
                    if e2.element_id not in nodes:
                        nodes[e2.element_id] = {
                            "id": e2.element_id,
                            "label": e2["name"],
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

            return GraphData(
                nodes=list(nodes.values()),
                edges=list(edges.values()),
            )

    def get_all_claims_for_session(self, session_id: str) -> list[dict]:
        with self.driver.session() as session:
            result = session.run(
                "MATCH (c:Claim {session_id: $session_id}) RETURN c ORDER BY c.id",
                session_id=session_id
            )
            return [{"id": r["c"]["id"], "text": r["c"]["text"]} for r in result]

    def update_claim(self, claim_id: str, new_text: str):
        with self.driver.session() as session:
            session.run(
                "MATCH (c:Claim {id: $id}) SET c.text = $text",
                id=claim_id, text=new_text
            )

    def delete_claim(self, claim_id: str):
        with self.driver.session() as session:
            session.run(
                "MATCH (c:Claim {id: $id}) DETACH DELETE c",
                id=claim_id
            )

    def get_context_for_query(self, session_id: str, query: str) -> str:
        claims = self.get_all_claims_for_session(session_id)
        if not claims:
            return ""
        claim_texts = [c["text"] for c in claims]
        return "\n".join(f"- {t}" for t in claim_texts)
