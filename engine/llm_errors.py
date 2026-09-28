"""Exception types every stage's runner treats as transient (leave the
item where it was, retry later) rather than a crash. Gemini API failures
(rate limits, auth, server errors) surface as google.genai.errors.APIError,
but a failure before an HTTP response ever arrives — DNS, connection
refused, timeout — surfaces as a raw httpx error instead; both need to be
caught the same way, in every stage, or the "one failure never aborts the
run" guarantee silently breaks for whichever stage forgot one of them.
"""
from __future__ import annotations

import httpx
from google.genai import errors

TRANSIENT_LLM_ERRORS = (errors.APIError, httpx.HTTPError)
