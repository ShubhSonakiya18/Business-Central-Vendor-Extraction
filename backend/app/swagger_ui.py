"""Swagger UI page whose Authorize popup works with the app's JSON login.

Why this exists
---------------
`POST /auth/login` takes JSON ({"email", "password"}). Protected routes declare
`OAuth2PasswordBearer(tokenUrl="auth/login")`, so Swagger's Authorize popup
runs the OAuth2 *password flow*, which the OpenAPI spec and Swagger UI fix to a
form-encoded body (`grant_type`, `username`, `password`). That request gets a
422 from /auth/login, and the spec cannot describe a JSON token request.

Swagger UI passes every request, including the popup's token request, through
a page-supplied `requestInterceptor`. This module serves /docs with an
interceptor that rewrites ONLY that one request into the app's real login
contract before it leaves the browser:

    form:  grant_type=password&username=<email>&password=<pw>
      ->   JSON {"email": "<email>", "password": "<pw>"}

Swagger then stores the returned `access_token` itself and sends
`Authorization: Bearer <access_token>` on protected calls.

This is browser-side only. The server, /auth/login, JWT creation and
validation, and every 401 are unchanged, and no second login endpoint exists.
The OpenAPI document is unchanged too (still OAuth2 password, tokenUrl
auth/login), so non-Swagger clients see exactly what they saw before.
"""

from __future__ import annotations

from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse

# Swagger UI calls this with its request object ({url, method, headers, body}).
# Only a form-encoded password-grant POST to .../auth/login is rewritten;
# anything else (Try-it-out on /auth/login, every other call) is returned as is.
# A failure inside the shim must never block a request, hence the try/catch.
TOKEN_REQUEST_INTERCEPTOR_JS = """function (req) {
  try {
    var path = new URL(req.url, window.location.href).pathname;
    var headers = req.headers || {};
    var ctKey = Object.keys(headers).filter(function (k) {
      return k.toLowerCase() === 'content-type';
    })[0];
    var contentType = ctKey ? String(headers[ctKey]).toLowerCase() : '';
    if (String(req.method).toUpperCase() === 'POST'
        && /\\/auth\\/login$/.test(path)
        && typeof req.body === 'string'
        && contentType.indexOf('application/x-www-form-urlencoded') === 0) {
      var form = new URLSearchParams(req.body);
      if (form.get('grant_type') === 'password') {
        req.body = JSON.stringify({
          email: form.get('username') || '',
          password: form.get('password') || ''
        });
        headers[ctKey] = 'application/json';
        Object.keys(headers).forEach(function (k) {
          if (k.toLowerCase() === 'authorization') { delete headers[k]; }
        });
      }
    }
  } catch (e) { /* never block a request because of this shim */ }
  return req;
}"""

# FastAPI's own page defines the config object as `SwaggerUIBundle({`; the
# interceptor is added as the first option so everything else stays FastAPI's.
_CONFIG_MARKER = "SwaggerUIBundle({"


def swagger_ui_response(openapi_url: str, title: str) -> HTMLResponse:
    html = get_swagger_ui_html(openapi_url=openapi_url, title=title).body.decode("utf-8")
    if _CONFIG_MARKER not in html:  # FastAPI changed its page: fail loudly, not silently
        raise RuntimeError("Unexpected Swagger UI page layout; cannot add the login interceptor")
    html = html.replace(
        _CONFIG_MARKER,
        _CONFIG_MARKER + "\n        requestInterceptor: " + TOKEN_REQUEST_INTERCEPTOR_JS + ",",
        1,
    )
    return HTMLResponse(html)
