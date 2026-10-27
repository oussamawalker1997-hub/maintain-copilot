"""Small SQL dialect boundary; business operations share the same transaction.

Only constant SQL templates contain {p}. Values always remain driver parameters.
Runtime PostgreSQL repositories use real site roles; explicit fixture provisioning is separate.
"""

import json
import re
import sqlite3


class Repository:
    def __init__(self, connection, site=None):
        self.connection = connection
        self.postgres = not isinstance(connection, sqlite3.Connection)
        self.site = site
        self.locked = False

    def query(self, template, parameters=()):
        return self.connection.execute(
            template.format(p="%s" if self.postgres else "?"), parameters
        )

    def write_lock(self):
        if self.postgres:
            if not self.locked:
                # Deliberately coarse per-site serialization for the local baseline.
                self.query("SELECT pg_advisory_xact_lock(714203002, {p})", (self.site_number,))
                self.locked = True
        elif not self.connection.in_transaction:
            self.connection.execute("BEGIN IMMEDIATE")

    @property
    def site_number(self):
        return {"DE-A": 1, "DE-B": 2}[self.site]

    def insert(self, table, values, *, ignore_conflict=False):
        values = dict(values)
        if self.postgres:
            if "site" in values and values["site"] != self.site:
                raise ValueError("Repository/site mismatch")
            values = {"site": self.site} | values
            if table == "runs":
                from psycopg.types.json import Jsonb

                values["result"] = Jsonb(json.loads(values["result"]))
            for key in ("active", "useful"):
                if key in values:
                    values[key] = bool(values[key])
        # Identifiers come from application code, never from request fields.
        if not all(re.fullmatch(r"[a-z_]+", name) for name in (table, *values)):
            raise ValueError("Invalid internal SQL identifier")
        placeholders = ",".join(["{p}"] * len(values))
        conflict = " ON CONFLICT DO NOTHING" if ignore_conflict else ""
        return self.query(
            f"INSERT INTO {table} ({','.join(values)}) VALUES ({placeholders}){conflict}",
            tuple(values.values()),
        )

    def search_pages(self, terms, site, model, hardware):
        if not self.postgres:
            match = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)
            return self.query(
                """SELECT p.number,p.text,d.* FROM page_fts
                JOIN pages p ON p.id=page_fts.rowid JOIN documents d ON d.id=p.document_id
                WHERE page_fts MATCH {p} AND d.site={p} AND d.status='published'
                AND d.model={p} AND d.hardware={p} ORDER BY bm25(page_fts),d.id,p.number""",
                (match, site, model, hardware),
            ).fetchall()
        query = " || ".join(["plainto_tsquery('simple', {p})"] * len(terms))
        return self.query(
            f"""WITH lookup AS (SELECT ({query}) AS terms)
            SELECT p.number,p.text,d.* FROM pages p
            JOIN documents d ON (d.site,d.id)=(p.site,p.document_id) CROSS JOIN lookup
            WHERE p.search_vector @@ lookup.terms AND d.site={{p}} AND d.status='published'
            AND d.model={{p}} AND d.hardware={{p}}
            ORDER BY ts_rank(p.search_vector,lookup.terms) DESC,d.id,p.number""",
            (*terms, site, model, hardware),
        ).fetchall()


def repository(connection):
    return connection if isinstance(connection, Repository) else Repository(connection)
