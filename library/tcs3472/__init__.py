"""Library for the TCS3472 colour light to digital converter with IR filter."""
import time
from collections import namedtuple

from i2cdevice import Device, Register, BitField
from i2cdevice.adapter import Adapter, LookupAdapter, U16ByteSwapAdapter

__version__ = '0.0.1'


I2C_ADDR = 0x29
I2C_COMMAND = 0x80
I2C_AUTOINC = 0x20
CHIP_ID = (0x44, 0x4d)


class IntegrationTimeAdapter(Adapter):
    def _encode(self, value):
        value = 256 - int(value / 2.4)
        return max(0, min(255, value))

    def _decode(self, value):
        value = (256 - value) * 2.4
        return max(0, min(614, value))


class WaitTimeAdapter(Adapter):
    def _encode(self, value):
        value = 256 - int(value / 2.4)
        return max(0, min(255, value))

    def _decode(self, value):
        value = (256 - value) * 2.4
        return max(0, min(614, value))


class TCS3472:
    def __init__(self, i2c_dev=None):
        """Initialise the TCS3472."""

        self._max_count = 0
        self._integration_time_ms = 0
        self._rgbc_tuple = namedtuple('Colour', (
            'time',
            'red',
            'green',
            'blue',
            'raw_red',
            'raw_green',
            'raw_blue',
            'raw_clear'
        ))

        self._tcs3472 = Device(I2C_ADDR, i2c_dev=i2c_dev, bit_width=8, registers=(
            Register('ENABLE', I2C_COMMAND | 0x00, fields=(
                BitField('power_on', 0b00000001),
                BitField('enable', 0b00000010),
                BitField('wait_enable', 0b00001000),
                BitField('int_enable', 0b00010000)
            )),
            # Actual integration time is (256 - INTEGRATION_TIME) * 2.4
            # Integration time affects the max ADC count, with the max count
            # being (256 - INTEGRATION_TIME) * 1024 up to a limit of 65535.
            # IE: An integration time of 0xF6 (24ms) would limit readings to 0-10240.
            Register('INTEGRATION_TIME', I2C_COMMAND | 0x01, fields=(
                BitField('time_ms', 0xff, adapter=IntegrationTimeAdapter()),  
            )),
            # Actual wait time is (256 - WAIT_TIME) * 2.4
            # if the WLONG bit is set, this value is multiplied by 12
            Register('WAIT_TIME', I2C_COMMAND | 0x03, fields=(
                BitField('time_ms', 0xff, adapter=WaitTimeAdapter()),
            )),
            Register('INTERRUPT_THRESHOLD', I2C_COMMAND | I2C_AUTOINC | 0x04, fields=(
                BitField('low', 0x0000ffff),
                BitField('high', 0xffff0000)
            ), bit_width=8 * 4),
            Register('PERSISTENCE', I2C_COMMAND | 0x0c, fields=(
                BitField('count', 0x0f, adapter=LookupAdapter({
                    0: 0b0000,
                    1: 0b0001,
                    2: 0b0010,
                    3: 0b0011,
                    5: 0b0100,
                    10: 0b0101,
                    15: 0b0110,
                    20: 0b0111,
                    25: 0b1000,
                    30: 0b1001,
                    35: 0b1010,
                    40: 0b1011,
                    45: 0b1100,
                    50: 0b1101,
                    55: 0b1110,
                    60: 0b1111
                })),
            )),
            # wlong multiplies the wait time by 12
            Register('CONFIGURATION', I2C_COMMAND | 0x0d, fields=(
                BitField('wlong', 0b00000010),    
            )),
            Register('CONTROL', I2C_COMMAND | 0x0f, fields=(
                BitField('gain', 0b00000011, adapter=LookupAdapter({
                    1: 0b00,
                    4: 0b01,
                    16: 0b10,
                    60: 0b11
                })),   
            )),
            # Should be either 0x44 (TCS34725) or 0x4D (TCS34727)
            Register('ID', I2C_COMMAND | 0x12, fields=(
                BitField('id', 0xff),    
            )),
            Register('STATUS', I2C_COMMAND | 0x13, fields=(
                BitField('aint', 0b00010000),
                BitField('avalid', 0b00000001)
            )),
            Register('RGBC', I2C_COMMAND | I2C_AUTOINC | 0x14, fields=(
                BitField('clear', 0xffff, adapter=U16ByteSwapAdapter()),
                BitField('red', 0xffff << 16, adapter=U16ByteSwapAdapter()),
                BitField('green', 0xffff << 32, adapter=U16ByteSwapAdapter()),
                BitField('blue', 0xffff << 48, adapter=U16ByteSwapAdapter())
            ), bit_width=8 * 8)
        ))

        chip = self._tcs3472.get('ID')

        if chip.id not in CHIP_ID:
            raise RuntimeError("TCS3472 not found! Chip ID {} not in {}".format(chip.id, CHIP_ID))

        # Enable the sensor and RGBC interface by default
        self._tcs3472.set('ENABLE', power_on=True, enable=True)

        # Aim for 100ms integration time, or 10 readings / second
        # This should give a saturation of ~41984 counts: (256 - 0xd7) * 1024
        # During testing it reached saturation at 41984
        self.set_integration_time_ms(100)
    
    def set_wait_time_ms(self, value, wait_long=False):
        self._tcs3472.set('WAIT_TIME', time_ms=value)
        self._tcs3472.set('CONFIGURATION', wlong=wait_long)

    def set_integration_time_ms(self, value):
        """Set the sensor integration time in milliseconds.
        
        :param value: Time in milliseconds from 0 to 614.
        
        """
        self._tcs3472.set('INTEGRATION_TIME', time_ms=value)
        # Calculate the max ADC count using the converted integration time.
        # This is used to scale ADC readings.
        self._max_count = int((256 - IntegrationTimeAdapter()._encode(value)) * 1024)
        self._max_count = min(65535, self._max_count)
        self._integration_time_ms = value

    def get_rgbc_counts(self):
        while not self._tcs3472.get('STATUS').avalid:
            time.sleep(0.0001)
        return self._tcs3472.get('RGBC')

    def get_rgbc(self):
        rgbc = self.get_rgbc_counts()

        scale = max(rgbc)

        try:
            return self._rgbc_tuple(
                time.time(),
                int((float(rgbc.red) / scale) * 255),
                int((float(rgbc.green) / scale) * 255),
                int((float(rgbc.blue) / scale) * 255),
                float(rgbc.red) / self._max_count,
                float(rgbc.green) / self._max_count,
                float(rgbc.blue) / self._max_count,
                float(rgbc.clear) / self._max_count
            )
        except ZeroDivisionError:
            return self._rgbc_tuple(
                time.time(),
                0,
                0,
                0,
                float(rgbc.red) / self._max_count,
                float(rgbc.green) / self._max_count,
                float(rgbc.blue) / self._max_count,
                float(rgbc.clear) / self._max_count
            )
