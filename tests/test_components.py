import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from haystack import Pipeline
from haystack.utils import Secret

from magic_hour_haystack import (
    MagicHourImageDownloader,
    MagicHourImageGenerator,
    MagicHourImageWaiter,
)

KEY = "mh_test_key"
MEDIA = "https://videos.magichour.ai/out.png?X-Goog-Signature=abc"
PNG = b"\x89PNG\r\n\x1a\nimage"


def project(status, downloads=None):
    return {"id": "img-1", "status": status, "credits_charged": 5, "downloads": downloads or []}


class FakeApi:
    """Stands in for urllib's opener, answering from a list of responses in order."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def build_opener(self, *handlers):
        return self

    def open(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        body = response if isinstance(response, bytes) else json.dumps(response).encode()
        return io.BytesIO(body)


def http_error(code):
    return HTTPError("https://api.magichour.ai", code, "error", {}, None)


class ComponentTests(unittest.TestCase):
    def run_with(self, api, component, **inputs):
        with patch("magic_hour_haystack.components.build_opener", api.build_opener):
            return component.run(**inputs)

    def test_generator_sends_one_image_request_and_returns_the_project(self):
        api = FakeApi({"id": "img-1", "credits_charged": 5})
        result = self.run_with(api, MagicHourImageGenerator(Secret.from_token(KEY)), prompt="A mug")
        self.assertEqual(result, {"project_id": "img-1", "credits_charged": 5})
        [request] = api.requests
        self.assertEqual(request.full_url, "https://api.magichour.ai/v1/ai-image-generator")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), f"Bearer {KEY}")
        self.assertEqual(json.loads(request.data)["style"], {"prompt": "A mug"})

    def test_generator_rejects_a_blank_prompt_before_any_request(self):
        api = FakeApi()
        with self.assertRaises(ValueError):
            self.run_with(api, MagicHourImageGenerator(Secret.from_token(KEY)), prompt="  ")
        self.assertEqual(api.requests, [])

    # A paid request may have been accepted before it failed, so it must not be sent again.
    def test_generator_sends_a_failed_request_once(self):
        api = FakeApi(http_error(500))
        with self.assertRaises(RuntimeError):
            self.run_with(api, MagicHourImageGenerator(Secret.from_token(KEY)), prompt="A mug")
        self.assertEqual(len(api.requests), 1)

    def test_waiter_polls_until_complete(self):
        done = project("complete", [{"url": MEDIA}])
        api = FakeApi(project("queued"), project("rendering"), done)
        waiter = MagicHourImageWaiter(Secret.from_token(KEY), poll_interval=0.001)
        self.assertEqual(self.run_with(api, waiter, project_id="img-1"), {"project": done})
        self.assertEqual(
            [r.full_url for r in api.requests],
            ["https://api.magichour.ai/v1/image-projects/img-1"] * 3,
        )

    # The job is paid for, so every failure must name the project to resume it.
    def test_waiter_failures_name_the_project(self):
        for response, error in [
            (project("error"), RuntimeError),
            (project("complete"), RuntimeError),
            (http_error(500), RuntimeError),
            (URLError("connection reset"), RuntimeError),
            (project("rendering"), TimeoutError),
        ]:
            with self.subTest(response=response):
                waiter = MagicHourImageWaiter(Secret.from_token(KEY), timeout=0.001)
                with self.assertRaises(error) as raised:
                    self.run_with(FakeApi(response, response), waiter, project_id="img-1")
                self.assertIn("img-1", str(raised.exception))

    def test_downloader_returns_the_images_without_the_api_key(self):
        api = FakeApi(PNG)
        result = self.run_with(
            api, MagicHourImageDownloader(), project=project("complete", [{"url": MEDIA}])
        )
        self.assertEqual(result["images"][0].data, PNG)
        self.assertEqual(result["project_id"], "img-1")
        [request] = api.requests
        self.assertEqual(request.full_url, MEDIA)
        self.assertIsNone(request.get_header("Authorization"))

    def test_downloader_rejects_urls_off_the_media_host(self):
        for url in [
            "http://videos.magichour.ai/out.png",
            "https://attacker.example/out.png",
            "https://user:pass@videos.magichour.ai/out.png",
        ]:
            with self.subTest(url=url):
                api = FakeApi()
                with self.assertRaises(ValueError):
                    self.run_with(
                        api, MagicHourImageDownloader(), project=project("complete", [{"url": url}])
                    )
                self.assertEqual(api.requests, [])

    # Saved pipelines must hold the environment variable's name, never the key.
    def test_serialization_keeps_the_key_out_of_saved_pipelines(self):
        pipeline = Pipeline()
        pipeline.add_component("generate", MagicHourImageGenerator())
        pipeline.add_component("wait", MagicHourImageWaiter(timeout=30))
        with patch.dict("os.environ", {"MAGIC_HOUR_API_KEY": KEY}):
            saved = pipeline.dumps()
            loaded = Pipeline.loads(saved, allowed_modules=["magic_hour_haystack.components"])
        self.assertNotIn(KEY, saved)
        self.assertIn("MAGIC_HOUR_API_KEY", saved)
        self.assertEqual(loaded.get_component("wait").timeout, 30)


if __name__ == "__main__":
    unittest.main()
