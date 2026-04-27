from scripts.farewell import farewell


def test_farewell():
    assert farewell() == "goodbye, world"
