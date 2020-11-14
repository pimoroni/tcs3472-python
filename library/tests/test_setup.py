import pytest


def test_setup_not_present(smbus, TCS3472):
    with pytest.raises(RuntimeError):
        TCS3472()


def test_setup(smbus, TCS3472):
    smbus.smbusdev.fake_chipid()
    TCS3472()