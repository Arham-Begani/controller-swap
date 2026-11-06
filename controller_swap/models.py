"""Optional OpenAI-compatible model connector. Disabled unless explicitly enabled.

Keys are read only on the server. Fixtures bypass this adapter. Tests use mocks
or a deterministic loopback HTTP service, never an external model.
"""
import json
import math
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .core import canonical, digest


def connector_status():
    base = os.getenv("CS_MODEL_BASE_URL", "")
    models = [os.getenv("CS_WORKER_A", ""), os.getenv("CS_WORKER_B", "")]
    return {"configured": bool(base and all(models)), "distinct_workers": bool(all(models) and models[0] != models[1])}


class ModelRequestError(ValueError):
    def __init__(self, message, kind):
        super().__init__(message)
        self.kind = kind


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Model endpoint redirects are disabled; configure its final URL")


class ModelConnector:
    def __init__(self, enabled=False, max_calls=50):
        self.enabled, self.max_calls, self.calls = enabled, max_calls, 0
        self.last_response_metadata = None
        self.opener = urllib.request.build_opener(NoRedirect)

    def ask(self, role, instruction, payload, *, output_schema=None):
        self.last_response_metadata = None
        if role not in ("worker_a", "worker_b", "supervisor", "evaluator"):
            raise ValueError("Unknown model role")
        if not self.enabled:
            raise ValueError("Live model calls are disabled. This build makes no paid calls by default.")
        if not connector_status()["configured"]:
            raise ValueError("Set CS_MODEL_BASE_URL, CS_WORKER_A and CS_WORKER_B on the server first.")
        if self.calls >= self.max_calls:
            raise ValueError("The server's live-call limit has been reached.")
        base = os.environ["CS_MODEL_BASE_URL"].rstrip("/")
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Model base URL must be HTTP(S) without embedded credentials.")
        if parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("Remote model endpoints require HTTPS.")
        model = os.getenv("CS_SUPERVISOR", os.environ["CS_WORKER_A"]) if role == "supervisor" else os.getenv("CS_EVALUATOR", os.environ["CS_WORKER_A"]) if role == "evaluator" else os.environ["CS_WORKER_A" if role == "worker_a" else "CS_WORKER_B"]
        token_parameter = os.getenv("CS_TOKEN_PARAMETER", "max_completion_tokens")
        if token_parameter not in ("max_completion_tokens", "max_tokens"):
            raise ValueError("CS_TOKEN_PARAMETER must be max_completion_tokens or max_tokens")
        try:
            token_limit = int(os.getenv("CS_MAX_COMPLETION_TOKENS", "1024"))
        except ValueError as error:
            raise ValueError("Completion token limit must be an integer") from error
        if not 128 <= token_limit <= 8192:
            raise ValueError("Completion token limit must be between 128 and 8192")
        options = {token_parameter: token_limit}
        response_format = os.getenv("CS_RESPONSE_FORMAT", "none")
        if response_format not in ("none", "json_object", "json_schema"):
            raise ValueError("CS_RESPONSE_FORMAT must be none, json_object or json_schema")
        if response_format == "json_schema" and output_schema is not None:
            options["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "controller_attribution", "strict": True, "schema": output_schema}}
        elif response_format in ("json_object", "json_schema"):
            options["response_format"] = {"type": "json_object"}
        if os.getenv("CS_TEMPERATURE"):
            try:
                temperature = float(os.environ["CS_TEMPERATURE"])
            except ValueError as error:
                raise ValueError("Temperature must be a finite number from 0 to 2") from error
            if not math.isfinite(temperature) or not 0 <= temperature <= 2:
                raise ValueError("Temperature must be a finite number from 0 to 2")
            options["temperature"] = temperature
        if os.getenv("CS_SEED"):
            try:
                seed = int(os.environ["CS_SEED"])
            except ValueError as error:
                raise ValueError("Seed must be an integer from 0 to 2147483647") from error
            if not 0 <= seed <= 2**31 - 1:
                raise ValueError("Seed must be an integer from 0 to 2147483647")
            options["seed"] = seed
        try:
            timeout_seconds = int(os.getenv("CS_REQUEST_TIMEOUT_SECONDS", "45"))
        except ValueError as error:
            raise ValueError("Request timeout must be an integer from 5 to 180 seconds") from error
        if not 5 <= timeout_seconds <= 180:
            raise ValueError("Request timeout must be an integer from 5 to 180 seconds")
        if role == "evaluator" and os.getenv("CS_EVALUATOR_TIMEOUT_SECONDS"):
            try:
                timeout_seconds = int(os.environ["CS_EVALUATOR_TIMEOUT_SECONDS"])
            except ValueError as error:
                raise ValueError("Evaluator timeout must be an integer from 5 to 900 seconds") from error
            if not 5 <= timeout_seconds <= 900:
                raise ValueError("Evaluator timeout must be an integer from 5 to 900 seconds")
        messages = [{"role": "system", "content": instruction}, {"role": "user", "content": canonical(payload)}]
        data = json.dumps({"model": model, "messages": messages, **options}).encode()
        headers = {"Content-Type": "application/json"}
        if os.getenv("CS_MODEL_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["CS_MODEL_API_KEY"]
        self.calls += 1
        request = urllib.request.Request(base + "/chat/completions", data=data, headers=headers, method="POST")
        started = time.monotonic()
        self.last_response_metadata = {"configured_model": model, "reported_model": None,
            "identity_basis": "provider_report_not_independently_verified",
            "request_parameters": options, "messages_sha256": digest(messages),
            "request_timeout_seconds": timeout_seconds, "finish_reason": None, "usage": {}}
        try:
            with self.opener.open(request, timeout=timeout_seconds) as response:
                raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise ValueError("Model response exceeded the size limit")
                body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("Model response must be an object")
            choices = body.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
                raise ModelRequestError("Model request failed: malformed response choices", "response_format")
            choice = choices[0]
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            self.last_response_metadata = {"configured_model": model, "reported_model": body.get("model"),
                "identity_basis": "provider_report_not_independently_verified",
                "request_parameters": options, "messages_sha256": digest(messages), "request_timeout_seconds": timeout_seconds,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "finish_reason": choice.get("finish_reason"),
                "usage": {k: v for k, v in usage.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens") and type(v) is int}}
            if choice.get("finish_reason") == "length":
                raise ModelRequestError("Model response reached its token limit; no prediction was saved", "truncated")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Model response did not contain text")
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError("Model content must be a JSON object")
            return result
        except TimeoutError as error:
            raise ModelRequestError(f"Model request failed: timed out after {timeout_seconds} seconds", "timeout") from error
        except urllib.error.HTTPError as error:
            if error.code in (408, 504):
                raise ModelRequestError(f"Model endpoint reported a timeout (HTTP {error.code})", "timeout") from error
            raise ModelRequestError(f"Model endpoint returned HTTP {error.code}", "transport") from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelRequestError(f"Model request failed: timed out after {timeout_seconds} seconds", "timeout") from error
            raise ModelRequestError("Model request failed at the configured endpoint", "transport") from error
        except (OSError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
            # Never echo provider bodies, URLs, headers or key material to the browser.
            raise ModelRequestError("Model request failed or did not return the required JSON object", "response_format") from error
        finally:
            self.last_response_metadata["elapsed_seconds"] = round(time.monotonic() - started, 3)
