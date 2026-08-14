import pytest

from llmwiki import youtube


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "https://youtu.be/jNQXAC9IVRw",
    "https://www.youtube.com/shorts/jNQXAC9IVRw",
    "https://www.youtube.com/embed/jNQXAC9IVRw?feature=share",
    "jNQXAC9IVRw",
])
def test_video_id_forms(url):
    assert youtube.video_id(url) == "jNQXAC9IVRw"


def test_video_id_rejects_garbage():
    with pytest.raises(ValueError):
        youtube.video_id("https://example.com/not-a-video")


def test_timestamp_format():
    assert youtube._timestamp(0) == "00:00:00"
    assert youtube._timestamp(3661.9) == "01:01:01"


@pytest.mark.parametrize("given,expected", [
    ("@SomeChannel", "https://www.youtube.com/@SomeChannel/videos"),
    ("https://www.youtube.com/@SomeChannel", "https://www.youtube.com/@SomeChannel/videos"),
    ("https://www.youtube.com/@SomeChannel/videos", "https://www.youtube.com/@SomeChannel/videos"),
    ("SomeChannel", "https://www.youtube.com/@SomeChannel/videos"),
])
def test_normalize_channel_url(given, expected):
    assert youtube.normalize_channel_url(given) == expected
