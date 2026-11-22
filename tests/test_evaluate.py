import json

from app.evaluate import device_digits, score


def test_score_counts_matching_leading_wheels():
    assert score("3598661", "3598") == (4, 4)
    assert score("3508661", "3598") == (3, 4)
    assert score("?598661", "3598") == (3, 4)


def test_device_digits_reads_the_cameras_own_answer(tmp_path, gas):
    picture = tmp_path / "gas-1.jpg"
    picture.write_bytes(b"x")
    assert device_digits(picture, gas) == ""  # no .json next to it
    (tmp_path / "gas-1.json").write_text(json.dumps({"main": {"raw": "1N0.NN"}}))
    assert device_digits(picture, gas) == "001?0??"
    (tmp_path / "gas-1.json").write_text("not json")
    assert device_digits(picture, gas) == ""
    (tmp_path / "gas-1.json").write_text(json.dumps({"other": 1}))
    assert device_digits(picture, gas) == ""
