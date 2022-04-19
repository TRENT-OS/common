#!/usr/bin/python3

import abc  # abstract base class
import inspect
import os
import time
from functools import reduce

#===============================================================================
#===============================================================================

class RasPi_GPIO():
    """
                             +--------+
    3.3v                     |  1  2  |  5v
    BCM_GPIO_2, I2C_1_SDA    |  3  4  |  5v
    BCM_GPIO_3, I2C_1_SCL    |  5  6  |  GND
    BCM_GPIO_4               |  7  8  |  BCM_GPIO_14, TXD_0
    GND	                     |  9  10 |  BCM_GPIO_15, RXD_0
    BCM_GPIO_17              | 11  12 |  BCM_GPIO_18
    BCM_GPIO_27              | 13  14 |  GND
    BCM_GPIO_22              | 15  16 |  BCM_GPIO_23
    3.3v                     | 17  18 |  BCM_GPIO_24
    BCM_GPIO_10, SPI_0_MOSI  | 19  20 |  GND
    BCM_GPIO_9,  SPI_0_MISO  | 21  22 |  BCM_GPIO_25
    BCM_GPIO_11, SPI_0_CLK   | 23  24 |  BCM_GPIO_8, SPI_CE0
    GND                      | 25  26 |  BCM_GPIO_7, SPI_CE1
    ID EEPROM_I2C_SCL        | 27  28 |  ID_EEPROM_I2C_SDA
    BCM_GPIO_5               | 29  30 |  GND
    BCM_GPIO_6               | 31  32 |  BCM_GPIO_12
    BCM_GPIO_13              | 33  34 |  GND
    BCM_GPIO_19, SPI_1_MOSI  | 35  36 |  BCM_GPIO_16
    BCM_GPIO_26              | 37  38 |  BCM_GPIO_20, SPI_1_MISO
    GND                      | 39  40 |  BCM_GPIO_21, SPI_1_CLK
                             +--------+
    """

    GPIO_BASE_DIR = '/sys/class/gpio'
    BCM_GPIO = [4, 5, 6, 12, 16, 17, 18, 21, 23, 24, 25, 26, 27]
    # MASK = reduce(lambda m,b: m | (1 << b), BCM_GPIO, 0)

    #---------------------------------------------------------------------------
    def __init__(self):

        print('RasPi GPIO init ...')
        # disable GPIO pins
        filename = os.path.join(self.GPIO_BASE_DIR, 'unexport')
        for pin_id in self.BCM_GPIO:
            with open(filename, 'w') as f:
                f.write('{}\n'.format(pin_id))

        # enable GPIO pins
        filename = os.path.join(self.GPIO_BASE_DIR, 'export')
        for pin_id in self.BCM_GPIO:
            with open(filename, 'w') as f:
                f.write('{}\n'.format(pin_id))

        # enabling the GPIO function can take some time, so we need to retry
        # here a couple of times
        for pin_id in self.BCM_GPIO:
            filename = self.get_gpio_pin_filename(pin_id, 'direction')
            cnt = 0
            while True:
                try:
                    with open(filename, 'w') as f:
                        f.write('out\n')
                        f.flush()
                        #if cnt > 0: print('set pin {} as output, cnt={}'.format(pin_id, cnt))
                        break
                except:
                    # seem we have to wait some time before the setting become
                    # active
                    time.sleep(0.1)
                    cnt += 1

        # set all GPIO pin low. Note that enabling the GPIO direction can take
        # some time, so we need to retry here a couple of times. Test show that
        # setting the direction fir all pins first and then setting the value
        # work well enough that we almost never have to retry here
        for pin_id in self.BCM_GPIO:
            cnt = 0
            while True:
                try:
                    self.set_gpio_pin(pin_id, 0)
                    #if cnt > 0: print('set pin {} low, cnt={}'.format(pin_id, cnt))
                    break
                except:
                    time.sleep(0.1)
                    cnt += 1

        print('RasPi GPIO init done')


    #---------------------------------------------------------------------------
    def get_gpio_pin_filename(self, pin_id, name):
        return os.path.join(
                    self.GPIO_BASE_DIR,
                    'gpio{}'.format(pin_id),
                    name)

    #---------------------------------------------------------------------------
    def set_gpio_pin(self, pin_id, value):
        filename = self.get_gpio_pin_filename(pin_id, 'value')
        with open(filename, 'w') as f:
            f.write('{}\n'.format(value))
            f.flush()

    #---------------------------------------------------------------------------
    def write(self, mask):

        print('set GPIOs: {:x}'.format(mask))
        pin_id = 0
        while mask > 0:
            if not pin_id in self.BCM_GPIO:
                print('write: invalid GPIO pin {}'.format(pin_id))
            else:
                v = mask & 1
                #print('wite_pin: set pin {} to {}'.format(pin_id, v))
                self.set_gpio_pin(pin_id, mask & 1)

            mask >>= 1
            pin_id += 1


#===============================================================================
#===============================================================================

class Relay_Base(abc.ABC):
    """
    Abstract relay base class.
    """

    #---------------------------------------------------------------------------
    @abc.abstractmethod
    def get_manager(self):
        return None

    #---------------------------------------------------------------------------
    @abc.abstractmethod
    def prepare_state_on(self):
        pass

    #---------------------------------------------------------------------------
    @abc.abstractmethod
    def prepare_state_off(self):
        pass

    #---------------------------------------------------------------------------
    @abc.abstractmethod
    def apply_state(self):
        pass

    #---------------------------------------------------------------------------
    @abc.abstractmethod
    def set_on(self):
        pass

    #---------------------------------------------------------------------------
    @abc.abstractmethod
    def set_off(self):
        pass


#===============================================================================
#===============================================================================

class Relay_Dummy(Relay_Base):
    """
    A dummy relay that does nothing. Useful as placeholder until there is a
    real relay
    """
    pass

    #---------------------------------------------------------------------------
    def __init__(self):
        pass


    #---------------------------------------------------------------------------
    def get_manager(self):
        print('{}() not implemented'.format(inspect.stack()[1][3]))
        return None


    #---------------------------------------------------------------------------
    def prepare_state_on(self):
        print('{}() not implemented'.format(inspect.stack()[1][3]))


    #---------------------------------------------------------------------------
    def prepare_state_off(self):
        print('{}() not implemented'.format(inspect.stack()[1][3]))


    #---------------------------------------------------------------------------
    def apply_state(self):
        print('{}() not implemented'.format(inspect.stack()[1][3]))


    #---------------------------------------------------------------------------
    def set_on(self):
        print('{}() not implemented'.format(inspect.stack()[1][3]))


    #---------------------------------------------------------------------------
    def set_off(self):
        print('{}() not implemented'.format(inspect.stack()[1][3]))


#===============================================================================
#===============================================================================

class Relay(Relay_Base):
    """
    A relay from a relay board. Usually obtained from the relay board object
    via a get_relay(id) function. A relay can either be switched on and off
    immediately or its state can be prepared, so multiple relays are then
    switch on/off together atomically when the pending prepared state is
    applied
    """

    #---------------------------------------------------------------------------
    def __init__(self, relay_mgr, relay_id):
        self.relay_mgr = relay_mgr
        self.relay_id  = relay_id


    #---------------------------------------------------------------------------
    def get_manager(self):
        return self.relay_mgr


    #---------------------------------------------------------------------------
    # prepare the relay state on, but do not actually switch the relay on
    def prepare_state_on(self):
        self.relay_mgr.prepare_state_on(self.relay_id)


    #---------------------------------------------------------------------------
    # prepare the relay state off, but do not actually switch the relay off
    def prepare_state_off(self):
        self.relay_mgr.prepare_state_off(self.relay_id)


    #---------------------------------------------------------------------------
    # apply the prepared relay states
    def apply_state(self):
        self.relay_mgr.apply_state()


    #---------------------------------------------------------------------------
    # switch the relay on
    def set_on(self):
        self.relay_mgr.set_on(self.relay_id)


    #---------------------------------------------------------------------------
    # switch the relay off
    def set_off(self):
        self.relay_mgr.set_off(self.relay_id)


#===============================================================================
#===============================================================================

class Relay_Config():
    """
    A relay configuration groups multiple relays. These relays can even come
    from different relay boards
    """

    #---------------------------------------------------------------------------
    def __init__(self, relay_dict = {}):
        self.relay_list = []
        self.relay_mgr_list = []
        self.add_relays(relay_dict)


    #---------------------------------------------------------------------------
    def add_relays(self, relay_dict = {}):
        for name, handler in relay_dict.items():
            setattr(self, name, handler)
            self.relay_list.append(name)
            # relays may have a manager if they are part of a group of
            # multiple relays
            manager = handler.get_manager()
            if (manager is not None) and (manager not in self.relay_mgr_list):
                self.relay_mgr_list.append(manager)

    #---------------------------------------------------------------------------
    def check_relays_exist(self, str_list):
        for relay_name in str_list:
            if not relay_name in self.relay_list:
                return False

        return True

    #---------------------------------------------------------------------------
    def apply_state(self):
        for mgr in self.relay_mgr_list:
            mgr.apply_state()


    #---------------------------------------------------------------------------
    def set_all_off(self):
        for mgr in self.relay_mgr_list:
            mgr.set_all_off()


#===============================================================================
#===============================================================================

class Relay_Board:
    """
    General operation: Pull I/O low to switch relay on.

    Operation mode 1: relays are driven from I/O line
       Connect VCC and GND to the IO controller board.

    Operation mode 2: relays are driven from I/O board power source
      remove the jumper between JD-VCC and VCC. Connect VCC to the I/O
      controller's I/O power and JD-VCC to the power source of the I/O controller
      board. Connect GND to the I/O controllers GND

    Operation mode 3: galvanic isolation of I/Os:
      remove jumper between VCC and JD-VCC. Connect JD-VCC and GND to a
      separate power source. Connect VCC to the I/O board's VCC


                  +-------------+   +----------------------+-- JD-VCC --o
                  | optocoupler |   |                      |
        o-- VCC --|...       ...|---+        Relais -- R --+
                  | LED  =>  |  |              |
        o-- IO --+....       ...|--- R --- Transistor
                  |             |              |
                  +-------------+              +----------------- GND --o
    """


    #---------------------------------------------------------------------------
    def __init__(self, gpio, printer = None):

        self.printer = printer
        self.gpio = gpio

        # self.set_all_off()
        # self.test_relays()

        self.state = 0
        self.set_all_off()

        # self.test_relays()
        # raise Exception('debug halt')


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer: self.printer.print(msg)


    #---------------------------------------------------------------------------
    # return a relay object
    def get_relay(self, relay_id):
        return Relay(self, relay_id)


    #---------------------------------------------------------------------------
    def prepare_state_on(self, n):
        self.state |= (1 << n)


    #---------------------------------------------------------------------------
    def prepare_state_off(self, n):
        self.state &= ~(1 << n)


    #---------------------------------------------------------------------------
    def apply_state(self):
        # self.print('relay mask 0x{:02x}'.format(m))
        # pulling an I/O down switches the relay on. We support 8 relays
        self.gpio.write(~self.state & 0xFF)


    #---------------------------------------------------------------------------
    def set_on(self, n):
        self.prepare_state_on(n)
        self.apply_state()


    #---------------------------------------------------------------------------
    def set_off(self, n):
        self.prepare_state_off(n)
        self.apply_state()


    #---------------------------------------------------------------------------
    def set_multiple_on(self, arr):
        for n in arr: self.prepare_state_on(n)
        self.apply_state()


    #---------------------------------------------------------------------------
    def set_multiple_off(self, arr):
        for n in arr: self.prepare_state_off(n)
        self.apply_state()


    #---------------------------------------------------------------------------
    def set_state(self, m):
        self.state = m
        self.apply_state()


    #---------------------------------------------------------------------------
    def set_all_off(self):
        self.set_state(0)


    #---------------------------------------------------------------------------
    def test_relays(self):
        self.print('relay test')
        for n in range(0,8):
            self.print('{}'.format(n))
            self.set_on(n)
            time.sleep(0.5)
            self.set_all_off()
            time.sleep(0.2)

