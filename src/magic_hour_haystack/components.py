"""Image-only components. Creation and recovery are separate paid/read operations."""

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from haystack import component, default_from_dict, default_to_dict
from haystack.dataclasses import ByteStream
from haystack.utils import Secret, deserialize_secrets_inplace


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(request: Request) -> bytes:
    # A new opener has no shared cookies or credentials. TLS verification stays enabled.
    try:
        with build_opener(_NoRedirect()).open(request, timeout=60) as response:
            data = response.read(32 * 1024 * 1024 + 1)
    except HTTPError as error:
        raise RuntimeError(f"Magic Hour request failed (HTTP {error.code}).") from None
    except (URLError, TimeoutError):
        raise RuntimeError("Magic Hour request failed; check connectivity and saved project ID.") from None
    if len(data) > 32 * 1024 * 1024:
        raise RuntimeError("Magic Hour response exceeds the 32 MiB image limit.")
    return data


def _api(api_key: Secret, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    # Paths are constructed internally; neither host nor authorization can be overridden.
    request = Request(
        "https://api.magichour.ai/v1/" + path,
        data=None if body is None else json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + api_key.resolve_value(),
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="GET" if body is None else "POST",
    )
    return json.loads(_request(request))


@component
class MagicHourImageGenerator:
    """Create one Z-Image Turbo image. Save project_id before starting recovery.

    A successful call consumes Magic Hour credits. This component never retries
    creation. An interrupted request can have been accepted without a response;
    inspect the Developer Hub before manually creating another job.
    """

    def __init__(self, api_key: Secret = Secret.from_env_var("MAGIC_HOUR_API_KEY")):
        self.api_key = api_key

    def to_dict(self) -> dict[str, Any]:
        return default_to_dict(self, api_key=self.api_key.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MagicHourImageGenerator":
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    @component.output_types(project_id=str, credits_charged=int)
    def run(self, prompt: str) -> dict[str, Any]:
        if not prompt.strip():
            raise ValueError("Image prompt must not be empty.")
        result = _api(self.api_key, "ai-image-generator", {
            "model": "z-image-turbo",
            "image_count": 1,
            "resolution": "640px",
            "aspect_ratio": "1:1",
            "style": {"prompt": prompt},
        })
        return {"project_id": result["id"], "credits_charged": result["credits_charged"]}


@component
class MagicHourImageWaiter:
    """Poll an existing image project without creating or rebilling a generation.

    Timeout/failure messages preserve the project ID so callers can resume. A
    timeout does not cancel the paid job. Download URLs expire; poll again to
    obtain current URLs.
    """

    def __init__(
        self,
        api_key: Secret = Secret.from_env_var("MAGIC_HOUR_API_KEY"),
        timeout: float = 300,
        poll_interval: float = 5,
    ):
        if timeout <= 0 or poll_interval <= 0:
            raise ValueError("timeout and poll_interval must be positive.")
        self.api_key = api_key
        self.timeout = timeout
        self.poll_interval = poll_interval

    def to_dict(self) -> dict[str, Any]:
        return default_to_dict(
            self, api_key=self.api_key.to_dict(),
            timeout=self.timeout, poll_interval=self.poll_interval,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MagicHourImageWaiter":
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    @component.output_types(project=dict)
    def run(self, project_id: str) -> dict[str, Any]:
        if not project_id:
            raise ValueError("project_id must not be empty.")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                project = _api(self.api_key, "image-projects/" + quote(project_id, safe=""))
            except RuntimeError as error:
                raise RuntimeError(f"Image project {project_id}: {error}") from None
            status = project["status"]
            if status == "complete":
                if not project.get("downloads"):
                    raise RuntimeError(f"Image project {project_id} completed without downloads.")
                return {"project": project}
            if status in ("error", "canceled"):
                raise RuntimeError(f"Image project {project_id} ended with status {status}.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Image project {project_id} is {status}; resume with the same ID.")
            time.sleep(min(self.poll_interval, remaining))


@component
class MagicHourImageDownloader:
    """Download completed Magic Hour images as Haystack ByteStreams.

    No API key is accepted or sent. Only the observed Magic Hour media host is
    allowed; HTTPS redirects are rejected rather than followed.
    """

    @component.output_types(images=list[ByteStream], project_id=str)
    def run(self, project: dict) -> dict[str, Any]:
        if project.get("status") != "complete" or not project.get("downloads"):
            raise ValueError("A completed image project with downloads is required.")
        images = []
        for index, item in enumerate(project["downloads"]):
            url = item["url"]
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "videos.magichour.ai"
                or parsed.port not in (None, 443)
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("Image download must use HTTPS on videos.magichour.ai.")
            images.append(ByteStream(
                data=_request(Request(url, headers={"Accept": "image/*"})),
                meta={"project_id": project["id"], "image_index": index},
            ))
        return {"images": images, "project_id": project["id"]}
