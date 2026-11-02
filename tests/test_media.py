"""The media-neutral helpers of foley.sources.media keep their former video_* names (#215)."""

import pytest

from foley.sources import media, video

RENAMED = {
    "video_key": "media_key",
    "is_video_key": "is_media_key",
    "recorded_video_key": "recorded_media_key",
    "video_url": "media_url",
    "local_video_file": "local_media_file",
    "VideoInput": "MediaValue",
}
KEPT = ("MEDIA", "MEDIA_INPUTS", "MediaInput", "RemoteVideo", "keyed", "replayable",
        "remote_media_input", "is_url", "video_suffix", "audio_suffix", "audio_seconds")


@pytest.mark.parametrize("old, new", RENAMED.items())
def test_a_former_name_is_the_media_helper(old, new):
    assert getattr(video, old) is getattr(media, new)


@pytest.mark.parametrize("name", KEPT)
def test_a_moved_name_is_still_importable_from_video(name):
    assert getattr(video, name) is getattr(media, name)


def test_the_public_remote_video_is_the_media_one():
    import foley

    assert foley.RemoteVideo is media.RemoteVideo


def test_a_media_inputs_probe_is_looked_up_when_called(monkeypatch):
    monkeypatch.setattr(video, "video_seconds", lambda value: 7.0)
    monkeypatch.setattr(media, "audio_seconds", lambda value: 3.0)
    assert media.MEDIA["video"].seconds(b"x") == 7.0
    assert media.MEDIA["audio"].seconds(b"x") == 3.0
