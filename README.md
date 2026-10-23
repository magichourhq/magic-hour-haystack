# Magic Hour for Haystack

Generate an image, recover its accepted project, and download the result through native Haystack Pipeline components. This image-only integration uses Z-Image Turbo, creates one square 640-pixel image, and consumes Magic Hour credits.

## Install

Requires Python 3.11+ and Haystack 3.4.

```bash
git clone https://github.com/magichourhq/magic-hour-haystack.git
cd magic-hour-haystack
python -m pip install .
```

Create an API key in the [Magic Hour Developer Hub](https://magichour.ai/developer). Provide it as the `MAGIC_HOUR_API_KEY` environment variable through your secret manager. Do not put the key in source, command history, receipts, or Git.

## Run and resume

```bash
HAYSTACK_TELEMETRY_ENABLED=false python examples/image_pipeline.py --output-dir output/bird --submit-only
HAYSTACK_TELEMETRY_ENABLED=false python examples/image_pipeline.py --output-dir output/bird
```

The first command runs a native creation Pipeline and saves its accepted ID in `project.json` before any polling. The second command runs a separate status/download Pipeline using that ID. Repeating the second command retrieves the same job; it does not create another image. Use a new output directory only when you intentionally want another paid generation.

The example prints safe receipts with the project ID, charged credits, file size and SHA-256. Actual images are saved as `image-1.bin`; detect their format or rename after inspection. The output directory contains your private media and is ignored by Git.

## Components

- `MagicHourImageGenerator.run(prompt)`: one paid image submission; returns `project_id` and `credits_charged`.
- `MagicHourImageWaiter.run(project_id)`: polls the image project until completion, error, cancellation, or timeout. Timeout retains the ID and does not cancel the job.
- `MagicHourImageDownloader.run(project)`: downloads completed image outputs as Haystack `ByteStream` objects; no API key is accepted or sent.

```python
from haystack import Pipeline
from magic_hour_haystack import MagicHourImageWaiter, MagicHourImageDownloader

pipeline = Pipeline()
pipeline.add_component("wait", MagicHourImageWaiter())
pipeline.add_component("download", MagicHourImageDownloader())
pipeline.connect("wait.project", "download.project")
result = pipeline.run({"wait": {"project_id": "YOUR_SAVED_IMAGE_PROJECT_ID"}})
image_bytes = result["download"]["images"][0].data
```

Both authenticated components use Haystack's environment-backed `Secret`. Serialization stores the environment variable name, not its value. Token-backed Secrets cannot be serialized. Haystack 3.4 requires an explicit trusted-module allowlist when loading a serialized custom pipeline: `Pipeline.loads(saved_yaml, allowed_modules=["magic_hour_haystack.components"])`. Load only pipeline definitions you trust. API requests use the fixed `https://api.magichour.ai/v1` origin with verified TLS, no redirects and no creation retries. Media requests accept only HTTPS on the observed `videos.magichour.ai` download host, never attach API authorization, and reject redirects. Each response is limited to 32 MiB.

If creation loses its response, the service may already have accepted the job. Inspect your Developer Hub before creating again. The example cannot persist an ID the service did not return. If polling/download fails, keep `project.json` and rerun the recovery command. Download URLs are temporary; a fresh project lookup obtains current URLs.

Prompts and generated content go to Magic Hour as the core generation operation. No LLM provider is required. See [Magic Hour's privacy policy](https://magichour.ai/privacy-policy) and [API documentation](https://docs.magichour.ai/tools/image/image-generator). Haystack telemetry can be disabled with `HAYSTACK_TELEMETRY_ENABLED=false`.

## Scope and status

Image generation only. No video/audio tools, uploaded inputs, arbitrary API calls, configurable service origins, background schedules, or automatic generation retries. Native validation on Haystack 3.4.1: one paid submission (5 Magic Hour credits), followed by two separate recoveries of the same saved project and identical usable 640×640 PNG downloads. Source publication and community listing acceptance are separate stages; a catalog submission does not mean deepset has accepted it.

## License

MIT. Maintained by Magic Hour. Report issues through this repository.
