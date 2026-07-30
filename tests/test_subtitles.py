from violetrelay.services.subtitles import SubtitleTrack


def test_srt_parser_and_lookup(tmp_path):
    path = tmp_path / "captions.srt"
    path.write_text(
        "1\n00:00:01,000 --> 00:00:02,500\n<b>Hello</b> world\n\n"
        "2\n00:00:03.000 --> 00:00:04.000\nSecond line\n",
        encoding="utf-8",
    )
    track = SubtitleTrack.from_srt(path)
    assert track.text_at(999) == ""
    assert track.text_at(1000) == "Hello world"
    assert track.text_at(2500) == "Hello world"
    assert track.text_at(2750) == ""
    assert track.text_at(3500) == "Second line"


def test_invalid_blocks_are_skipped(tmp_path):
    path = tmp_path / "broken.srt"
    path.write_text("not a subtitle\n\n1\ninvalid --> time\nText", encoding="utf-8")
    assert SubtitleTrack.from_srt(path).cues == []
