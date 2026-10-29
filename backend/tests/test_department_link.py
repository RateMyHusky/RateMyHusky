"""The professor page links its department only to a department page that exists."""
import server

HUB = {"computer-science": {"slug": "computer-science", "name": "Computer Science"}}


def _identity(monkeypatch, department):
    payload = {"identity": {"slug": "olin-guha", "name": "Olin Guha", "department": department}}
    monkeypatch.setattr(server, "professor_payload", lambda slug: payload)
    monkeypatch.setattr(server, "_department_hub_map", lambda: HUB)
    with server.app.test_request_context("/api/professors/olin-guha/full"):
        out = server.professor_full("olin-guha").get_json()["identity"]
    return out, payload


def test_a_department_with_a_page_carries_its_slug(monkeypatch):
    out, _ = _identity(monkeypatch, "Computer Science")
    assert out["departmentSlug"] == "computer-science"


def test_a_department_without_a_page_carries_none(monkeypatch):
    # The hub has no page for a department without rated professors; linking it would 404.
    out, _ = _identity(monkeypatch, "Africana Studies")
    assert out["departmentSlug"] is None


def test_a_second_spelling_of_a_hub_slug_carries_none(monkeypatch):
    # "Computer & Science" slugs like "Computer Science", but the hub page lists only the
    # first-seen spelling, so this professor wouldn't be on it.
    monkeypatch.setattr(server, "department_slug", lambda name: "computer-science" if name else "")
    out, _ = _identity(monkeypatch, "Computer & Science")
    assert out["departmentSlug"] is None


def test_no_department_carries_none(monkeypatch):
    out, _ = _identity(monkeypatch, None)
    assert out["departmentSlug"] is None


def test_the_cached_payload_is_not_mutated(monkeypatch):
    # professor_payload returns the cached dict; writing into it would persist per process.
    _, payload = _identity(monkeypatch, "Computer Science")
    assert "departmentSlug" not in payload["identity"]
