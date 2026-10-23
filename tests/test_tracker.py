import shutil

import cv2
import pytest

from grindcap.config import Config, _merge, DEFAULT_CONFIG
from grindcap.events import EventDetector, Stabilizer
from grindcap.readers import BarReader, TextReader
from grindcap.session import Tracker, summarize

from synth import (HP_BOX, HP_RGB, MAX_HP, config_dict, draw, scripted_session)

HAS_TESS = shutil.which("tesseract") is not None


def make_cfg(**kw):
    return Config(_merge(DEFAULT_CONFIG, config_dict(**kw)))


class ListSource:
    def __init__(self, frames):
        self._f = frames

    def frames(self):
        yield from self._f


def test_stabilizer_needs_repeats():
    s = Stabilizer(2)
    assert s.push(10) is None
    assert s.push(10) == (None, 10)
    assert s.push(7) is None          # one-frame blip
    assert s.push(10) is None         # back to accepted value: no event
    assert s.push(7) is None
    assert s.push(7) == (10, 7)


@pytest.mark.parametrize("hp", [0, 1, 137, 500, 999, 1000])
def test_bar_reader_with_text_overlay(hp):
    r = BarReader(HP_BOX, HP_RGB, 45, MAX_HP)
    got = r.read(draw(hp, 200, 0, 0)).value
    assert abs(got - hp) <= MAX_HP / HP_BOX[2]  # within one pixel column


def test_hp_pair_slash_misread():
    assert (TextReader.parse_pair("112741127").value, TextReader.parse_pair("112741127").max) == (1127, 1127)
    assert TextReader.parse_pair("85411127").value == 854        # 854/1127
    assert TextReader.parse_pair("85411127").max == 1127
    assert TextReader.parse_pair("3124450").max == 450            # 312/450, slash read as 4
    assert TextReader.parse_pair("312/450").value == 312


def test_text_parse():
    assert TextReader.parse("53.791").value == 53791       # comma misread as a period
    assert TextReader.parse("53 791").value == 53791
    assert TextReader.parse("1.234.567").value == 1234567
    assert TextReader.parse("6.10%").value == 6               # a real decimal is left alone
    assert TextReader.parse("312/450").value == 312
    assert TextReader.parse("[312/450]").max == 450
    assert TextReader.parse("1,234,567").value == 1234567
    assert TextReader.parse("").value is None


def test_cast_matching():
    d = EventDetector(make_cfg())
    assert d.match_casts(4) == ["Power Strike"]
    assert d.match_casts(8) in (["Final Attack"], ["Power Strike", "Power Strike"])
    assert d.match_casts(12) is not None
    assert d.match_casts(5.5) is None


def test_events_from_values():
    d = EventDetector(make_cfg())
    seq = [
        (0.0, dict(hp=900, mp=380, exp=1000, mesos=5000)),
        (0.1, dict(hp=900, mp=380, exp=1000, mesos=5000)),
        (0.2, dict(hp=900, mp=376, exp=1000, mesos=5000)),
        (0.3, dict(hp=900, mp=376, exp=1000, mesos=5000)),
        (0.4, dict(hp=855, mp=376, exp=1000, mesos=5000)),
        (0.5, dict(hp=855, mp=376, exp=1000, mesos=5000)),
        (0.6, dict(hp=855, mp=376, exp=1052, mesos=5080)),  # two kills in one step
        (0.7, dict(hp=855, mp=376, exp=1052, mesos=5080)),
    ]
    kinds = [e for t, v in seq for e in d.process(t, v)]
    names = [e.kind for e in kinds]
    assert names == ["cast", "touch", "kill", "meso"]
    assert kinds[2].data["n"] == 2


def test_level_up_wrap():
    cfg = make_cfg()
    d = EventDetector(cfg)  # level 20 -> 20216 EXP to next
    out = []
    for t, v in [(0, 20200), (0.1, 20200), (0.2, 10), (0.3, 10)]:
        out += d.process(t, {"exp": v})
    assert [e.kind for e in out] == ["level_up", "kill"]
    assert out[1].data["exp"] == 26


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_scripted_session_end_to_end():
    frames, truth = scripted_session(n_kills=6)
    tr = Tracker(make_cfg(), ListSource(frames))
    s = summarize(tr.run())
    assert s["kills"] == truth["kills"]
    assert s["touches"] == truth["touches"]
    assert sum(s["casts"].values()) == truth["casts"]
    assert s["mesos_picked_up"] == truth["mesos"]
    assert s["touches_per_kill"] == 1.0
    assert s["fa_heal_hp"] == 30 * 2
    assert s["hp_potion_hp"] == 150
    assert s["secs_between_kills"] == pytest.approx(2.5, abs=0.3)


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_replay_from_video(tmp_path):
    from grindcap.capture import VideoSource

    frames, truth = scripted_session(n_kills=4)
    path = tmp_path / "session.avi"
    h, w = frames[0][1].shape[:2]
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 8, (w, h))
    for _, f in frames:
        vw.write(f)
    vw.release()
    s = summarize(Tracker(make_cfg(), VideoSource(str(path), fps=8)).run())
    assert s["kills"] == truth["kills"]
    assert s["touches"] == truth["touches"]


@pytest.mark.skipif(not HAS_TESS, reason="Tesseract not installed")
def test_real_game_exp_crop():
    """EXP number cropped from the real game (MapleStory Classic, 15 px tall)."""
    from pathlib import Path

    img = cv2.imread(str(Path(__file__).parent / "fixtures" / "exp_53791.png"))
    r = TextReader([0, 0, img.shape[1], img.shape[0]])
    assert r.read(img).value == 53791
