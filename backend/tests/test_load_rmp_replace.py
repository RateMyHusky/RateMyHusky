"""--replace: TRUNCATE and reload commit together, so the table is never empty.

PostgreSQL TRUNCATE is transactional. The old flow committed it on its own
before the reload began, which exposed an empty rmp_professors.
"""

import pytest

import load_rmp

CSV = ("name,department,rating,num_ratings,would_take_again_pct,level_of_difficulty,professor_url\n"
       "Prof One,Math,4.0,10,90%,2.0,https://a\n"
       "Prof Two,Physics,3.0,5,50%,3.0,https://b\n")


class Cur:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.events.append(("execute", sql))


class Conn:
    def __init__(self):
        self.events = []

    def cursor(self):
        return Cur(self.events)

    def commit(self):
        self.events.append(("commit",))

    def rollback(self):
        self.events.append(("rollback",))


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "rmp_professors.csv"
    path.write_text(CSV, encoding="utf-8")
    return str(path)


def test_replace_truncates_and_reloads_in_one_commit(csv_path, monkeypatch):
    conn = Conn()
    monkeypatch.setattr(load_rmp, "BATCH_SIZE", 1)  # force one INSERT per row
    monkeypatch.setattr(load_rmp, "execute_values",
                        lambda cur, sql, batch, page_size=None: cur.events.append(("insert", len(batch))))
    load_rmp.load_table(conn, "rmp_professors", csv_path, replace=True)
    assert conn.events[0] == ("execute", "TRUNCATE TABLE rmp_professors")
    assert [e for e in conn.events if e[0] == "insert"] == [("insert", 1), ("insert", 1)]
    assert conn.events.count(("commit",)) == 1
    assert conn.events[-1] == ("commit",)


def test_a_failed_reload_rolls_the_truncate_back(csv_path, monkeypatch):
    conn = Conn()

    def boom(cur, sql, batch, page_size=None):
        raise RuntimeError("insert failed")

    monkeypatch.setattr(load_rmp, "execute_values", boom)
    with pytest.raises(RuntimeError, match="insert failed"):
        load_rmp.load_table(conn, "rmp_professors", csv_path, replace=True)
    assert ("rollback",) in conn.events
    assert ("commit",) not in conn.events


def test_replace_refuses_a_missing_csv_before_truncating(tmp_path):
    conn = Conn()
    with pytest.raises(SystemExit, match="refusing to truncate"):
        load_rmp.load_table(conn, "rmp_professors", str(tmp_path / "absent.csv"), replace=True)
    assert conn.events == []


def test_no_schema_creation_code_remains():
    assert all("create_sql" not in conf for conf in load_rmp.TABLES.values())
    assert not hasattr(load_rmp, "create_table")
    assert not hasattr(load_rmp, "add_constraints")
