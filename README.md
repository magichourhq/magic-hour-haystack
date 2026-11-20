# Magic Hour for Haystack

Generate images with [Magic Hour](https://magichour.ai) in [Haystack](https://haystack.deepset.ai) pipelines. Creating an image and retrieving it are separate components, so you can save the project ID in between and resume a job without paying for it again.

It uses the `z-image-turbo` model and makes one square 640-pixel image per call.

## Install

```sh
pip install magic-hour-haystack
```

Requires Python 3.11 or newer and Haystack 3.0 or newer. Set `MAGIC_HOUR_API_KEY` to a key from your [Magic Hour developer dashboard](https://magichour.ai/developer).

## Components

| Component | Input | Output |
| --- | --- | --- |
| `MagicHourImageGenerator` | `prompt` | `project_id`, `credits_charged`. Starts one paid job. |
| `MagicHourImageWaiter` | `project_id` | `project`, once the job completes |
| `MagicHourImageDownloader` | `project` | `images` as `ByteStream`s, and `project_id` |

Save the project ID from the generator, then wait for and download it in a second pipeline:

```python
from haystack import Pipeline
from magic_hour_haystack import (
    MagicHourImageDownloader,
    MagicHourImageGenerator,
    MagicHourImageWaiter,
)

create = Pipeline()
create.add_component("generate", MagicHourImageGenerator())
project_id = create.run({"generate": {"prompt": "A tiny orange paper bird"}})["generate"]["project_id"]
# Save project_id somewhere durable before waiting.

fetch = Pipeline()
fetch.add_component("wait", MagicHourImageWaiter())
fetch.add_component("download", MagicHourImageDownloader())
fetch.connect("wait.project", "download.project")
images = fetch.run({"wait": {"project_id": project_id}})["download"]["images"]
```

Running the second pipeline again with the same ID retrieves the same image, with fresh download URLs. [examples/image_pipeline.py](examples/image_pipeline.py) does this from the command line, saving the ID to a file between the two steps.

`MagicHourImageWaiter` takes `timeout` (default 300 seconds) and `poll_interval` (default 5 seconds).

## Credits and failures

- **The generator never retries.** If its request fails, the job may still have been accepted, so check your Magic Hour projects before generating again.
- **Waiter errors name the project,** so you can run the waiter again with the same ID. A timeout doesn't cancel the job.
- **The API key only goes to `api.magichour.ai`.** The downloader sends no key, and only downloads over HTTPS from `videos.magichour.ai`. No request follows redirects.

## Saving pipelines

The components read the key from `MAGIC_HOUR_API_KEY`, and a saved pipeline stores only the variable's name. To load one, allow the module:

```python
Pipeline.loads(saved_yaml, allowed_modules=["magic_hour_haystack.components"])
```

## Development

```sh
pip install -e .
python -m unittest discover -s tests
```

The tests replace HTTP with a fake, so they spend no credits. Set `HAYSTACK_TELEMETRY_ENABLED=false` to stop Haystack sending usage data while you work.

## License

MIT
