import sys
import pytest
import mock


class MockSMBus:
    """Mock enough of the BME680 for the library to initialise and test."""

    def __init__(self, bus):
        """Initialise with test data."""
        self.regs = [0 for _ in range(256)]

    def fake_chipid(self):
        self.regs[0x80 | 0x12] = 0x44

    def read_byte_data(self, addr, register):
        """Read a single byte from fake registers."""
        return self.regs[register]

    def write_byte_data(self, addr, register, value):
        """Write a single byte to fake registers."""
        self.regs[register] = value

    def read_i2c_block_data(self, addr, register, length):
        """Read up to length bytes from register."""
        return self.regs[register:register + length]


@pytest.fixture(scope='function', autouse=False)
def TCS3472():
    from tcs3472 import TCS3472
    yield TCS3472
    del sys.modules['tcs3472']


@pytest.fixture(scope='function', autouse=False)
def smbus():
    """Mock smbus module."""
    smbus = mock.Mock()
    smbus.smbusdev = MockSMBus(1)
    smbus.SMBus(1).read_i2c_block_data.side_effect = smbus.smbusdev.read_i2c_block_data
    sys.modules['smbus'] = smbus
    yield smbus
    del sys.modules['smbus']