"""Swagger's Authorize popup against the app's existing JSON login.

The popup runs the OAuth2 password flow and sends a FORM body to /auth/login.
`app/swagger_ui.py` serves /docs with a requestInterceptor that rewrites only
that request into the app's real JSON contract. These tests check:

  * the interceptor itself (run in Node, on the exact request shape Swagger
    UI 5 builds -- buildFormData + the form Content-Type);
  * the rewritten request really logs in, and the token opens a protected route;
  * the server contract and every 401 are UNCHANGED (this file must not need a
    single behaviour change in /auth/login or get_current_user);
  * nothing here can reach Decentro or gstinapi.in.

The real-browser run (Chrome driving /docs) is a manual / temporary check, not
part of this suite.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from jose import jwt

from app.config.config import settings
from app.swagger_ui import TOKEN_REQUEST_INTERCEPTOR_JS

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")

EMAIL = "swagger.user@example.com"
PASSWORD = "pw-with+plus&amp=chars 123"     # characters that must survive form -> JSON


@pytest.fixture(autouse=True)
def _no_outbound_http(monkeypatch):
    """These tests must never call Decentro / gstinapi.in (or anything else).
    GSTIN_API_ENABLED is already forced off by conftest; this also turns any
    stray `requests` call into a failing test. TestClient uses httpx, so it is
    unaffected."""
    import requests

    def _blocked(*args, **kwargs):
        raise AssertionError("outbound HTTP via `requests` during an auth test")

    monkeypatch.setattr(requests.sessions.Session, "request", _blocked)
    assert settings.GSTIN_API_ENABLED is False


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def swagger_form_body(**fields: str) -> str:
    """Swagger UI 5's buildFormData: skip empty values, encodeURIComponent,
    then %20 -> '+'."""
    return "&".join(
        f"{k}={quote(v, safe='').replace('%20', '+')}" for k, v in fields.items() if v != ""
    )


def run_interceptor(request: dict) -> dict:
    """Run the real interceptor JS in Node against `request` (a Swagger UI
    request object) and return what it hands back."""
    script = (
        "globalThis.window = { location: { href: 'http://127.0.0.1:8000/docs' } };\n"
        f"const intercept = ({TOKEN_REQUEST_INTERCEPTOR_JS});\n"
        "let raw = '';\n"
        "process.stdin.on('data', d => raw += d);\n"
        "process.stdin.on('end', () => {\n"
        "  process.stdout.write(JSON.stringify(intercept(JSON.parse(raw))));\n"
        "});\n"
    )
    # Explicit UTF-8: Node writes UTF-8, and Python on Windows would otherwise
    # decode the pipe as cp1252.
    done = subprocess.run([NODE, "-e", script], input=json.dumps(request),
                          capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def popup_request(username: str = EMAIL, password: str = PASSWORD, **overrides) -> dict:
    """The request Swagger's Authorize popup builds for the token URL."""
    req = {
        "url": "http://127.0.0.1:8000/auth/login",
        "method": "post",
        "headers": {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Requested-With": "XMLHttpRequest",
        },
        "body": swagger_form_body(grant_type="password", scope="", username=username, password=password),
    }
    req.update(overrides)
    return req


def expired_access_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "type": "access",
               "exp": datetime.now(timezone.utc) - timedelta(minutes=1)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


@pytest.fixture
def account(client):
    r = client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# the interceptor (Node)
# ---------------------------------------------------------------------------

@needs_node
class TestInterceptor:
    def test_popup_token_request_becomes_the_apps_json_login(self):
        out = run_interceptor(popup_request())
        assert out["headers"]["Content-Type"] == "application/json"
        assert json.loads(out["body"]) == {"email": EMAIL, "password": PASSWORD}
        assert out["url"] == "http://127.0.0.1:8000/auth/login"
        assert out["method"] == "post"

    def test_special_characters_survive_the_rewrite(self):
        pw = "p+a&s=s %20 ünï/?#"
        out = run_interceptor(popup_request(password=pw))
        assert json.loads(out["body"])["password"] == pw

    def test_client_basic_authorization_header_is_dropped(self):
        req = popup_request()
        req["headers"]["Authorization"] = "Basic Y2xpZW50OnNlY3JldA=="
        assert "Authorization" not in run_interceptor(req)["headers"]

    def test_lowercase_content_type_header_is_handled(self):
        req = popup_request()
        req["headers"] = {"content-type": "application/x-www-form-urlencoded; charset=UTF-8"}
        out = run_interceptor(req)
        assert out["headers"]["content-type"] == "application/json"
        assert json.loads(out["body"])["email"] == EMAIL

    def test_trailing_path_and_absolute_or_relative_urls(self):
        for url in ("/auth/login", "http://example.test/auth/login", "https://x.ngrok.dev/auth/login"):
            out = run_interceptor(popup_request(url=url))
            assert json.loads(out["body"])["email"] == EMAIL, url

    @pytest.mark.parametrize("request_", [
        # Try-it-out on /auth/login already sends JSON: untouched
        {"url": "http://127.0.0.1:8000/auth/login", "method": "POST",
         "headers": {"Content-Type": "application/json"}, "body": '{"email":"a@b.c","password":"x"}'},
        # an ordinary protected call
        {"url": "http://127.0.0.1:8000/vendors/9", "method": "GET",
         "headers": {"Authorization": "Bearer abc"}},
        # form-encoded POST to some other endpoint
        {"url": "http://127.0.0.1:8000/auth/refresh", "method": "POST",
         "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "body": "grant_type=password&username=a&password=b"},
        # a different grant type
        {"url": "http://127.0.0.1:8000/auth/login", "method": "POST",
         "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "body": "grant_type=client_credentials&client_id=x"},
        # not a login path that merely ends similarly
        {"url": "http://127.0.0.1:8000/other/auth/login/extra", "method": "POST",
         "headers": {"Content-Type": "application/x-www-form-urlencoded"}, "body": "grant_type=password&username=a&password=b"},
    ])
    def test_every_other_request_is_returned_unchanged(self, request_):
        assert run_interceptor(request_) == request_

    def test_a_malformed_request_never_throws(self):
        assert run_interceptor({"method": "POST"}) == {"method": "POST"}


# ---------------------------------------------------------------------------
# the /docs page
# ---------------------------------------------------------------------------

class TestDocsPage:
    def test_docs_serves_swagger_ui_with_the_interceptor(self, client):
        r = client.get("/docs")
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
        assert "SwaggerUIBundle(" in r.text
        assert "requestInterceptor:" in r.text
        assert TOKEN_REQUEST_INTERCEPTOR_JS in r.text
        # same Swagger UI assets FastAPI serves by default
        assert "swagger-ui-dist@5/swagger-ui-bundle.js" in r.text

    def test_openapi_scheme_is_unchanged_oauth2_password(self, client):
        spec = client.get("/openapi.json").json()
        scheme = spec["components"]["securitySchemes"]["OAuth2PasswordBearer"]
        assert scheme["type"] == "oauth2"
        assert scheme["flows"]["password"]["tokenUrl"] == "auth/login"
        assert "email" in scheme["description"]          # tells the user what to type
        assert spec["paths"]["/vendors/{vendor_id}"]["get"]["security"] == [{"OAuth2PasswordBearer": []}]
        assert "/docs" not in spec["paths"]               # the page itself is not an API operation

    def test_login_is_still_documented_as_json_only(self, client):
        spec = client.get("/openapi.json").json()
        body = spec["paths"]["/auth/login"]["post"]["requestBody"]["content"]
        assert list(body) == ["application/json"]


# ---------------------------------------------------------------------------
# end to end: popup request -> interceptor -> real /auth/login -> Bearer -> /vendors/{id}
# ---------------------------------------------------------------------------

@needs_node
class TestSwaggerFlowEndToEnd:
    def test_popup_login_then_protected_call(self, auth_client_factory, account):
        client = auth_client_factory
        rewritten = run_interceptor(popup_request())
        r = client.post("/auth/login", content=rewritten["body"], headers=rewritten["headers"])
        assert r.status_code == 200, r.text
        tokens = r.json()
        assert tokens["token_type"] == "bearer"
        assert tokens["access_token"] and tokens["refresh_token"]

        # what Swagger does with it: Authorization: Bearer <access_token>
        vid = client.post("/vendors", json={"vendor_name": "Swagger Test Pvt Ltd"},
                          headers=bearer(tokens["access_token"])).json()["id"]
        ok = client.get(f"/vendors/{vid}", headers=bearer(tokens["access_token"]))
        assert ok.status_code == 200
        assert ok.json()["vendor_name"] == "Swagger Test Pvt Ltd"

    def test_wrong_password_through_the_popup_still_fails(self, client, account):
        rewritten = run_interceptor(popup_request(password="not-the-password"))
        r = client.post("/auth/login", content=rewritten["body"], headers=rewritten["headers"])
        assert r.status_code == 401
        assert r.json() == {"detail": "Invalid email or password"}

    def test_unknown_email_through_the_popup_still_fails(self, client, account):
        rewritten = run_interceptor(popup_request(username="nobody@example.com"))
        assert client.post("/auth/login", content=rewritten["body"],
                           headers=rewritten["headers"]).status_code == 401


# ---------------------------------------------------------------------------
# existing runtime behaviour, unchanged
# ---------------------------------------------------------------------------

class TestAuthBehaviourUnchanged:
    def test_login_json_contract_still_200(self, client, account):
        r = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        assert r.status_code == 200
        assert set(r.json()) == {"access_token", "refresh_token", "token_type"}

    def test_login_wrong_credentials_still_401(self, client, account):
        r = client.post("/auth/login", json={"email": EMAIL, "password": "wrong"})
        assert (r.status_code, r.json()) == (401, {"detail": "Invalid email or password"})

    def test_login_form_body_is_still_rejected_by_the_server(self, client, account):
        """The server contract did NOT change: only the browser-side shim
        converts Swagger's form request. A raw form is still a 422."""
        r = client.post("/auth/login", content=swagger_form_body(grant_type="password", username=EMAIL, password=PASSWORD),
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 422

    def test_protected_route_without_a_token(self, client):
        r = client.get("/vendors/9")
        assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"})
        assert r.headers["www-authenticate"] == "Bearer"

    @pytest.mark.parametrize("header", [
        {"Authorization": "Bearer not-a-jwt"},
        {"Authorization": "Bearer a.b.c"},
        {"Authorization": "Bearer "},
    ])
    def test_invalid_or_malformed_token(self, client, header):
        r = client.get("/vendors/9", headers=header)
        assert (r.status_code, r.json()) == (401, {"detail": "Could not validate credentials"})

    def test_wrong_scheme(self, client):
        r = client.get("/vendors/9", headers={"Authorization": "Basic abc"})
        assert (r.status_code, r.json()) == (401, {"detail": "Not authenticated"})

    def test_expired_access_token(self, client, account):
        r = client.get("/vendors/9", headers=bearer(expired_access_token(account["id"])))
        assert (r.status_code, r.json()) == (401, {"detail": "Could not validate credentials"})

    def test_refresh_token_is_not_an_access_token(self, client, account):
        tokens = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()
        r = client.get("/vendors/9", headers=bearer(tokens["refresh_token"]))
        assert r.status_code == 401

    def test_valid_token_is_accepted(self, client, account):
        token = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()["access_token"]
        vid = client.post("/vendors", json={"vendor_name": "Valid Token Ltd"}, headers=bearer(token)).json()["id"]
        assert client.get(f"/vendors/{vid}", headers=bearer(token)).status_code == 200
        # a vendor that does not exist is a 404 for an authenticated caller, not a 401
        assert client.get("/vendors/987654", headers=bearer(token)).status_code == 404


@pytest.fixture
def auth_client_factory(client):
    """The plain `client` (no pre-set Authorization header), so the test
    controls exactly which headers each call sends."""
    return client
