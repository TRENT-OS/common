#!/usr/bin/python3

import time


#===============================================================================
#===============================================================================

class Relay(object):
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
    """
    A dummy relay, the object provides all function but does nothing. This is
    easier top use than "None".
    """

class Relay_Dummy(object):

    #---------------------------------------------------------------------------
    def __init__(self):
        pass


    #---------------------------------------------------------------------------
    def get_manager(self):
        return None


    #---------------------------------------------------------------------------
    def prepare_state_on(self):
        pass


    #---------------------------------------------------------------------------
    def prepare_state_off(self):
        pass


    #---------------------------------------------------------------------------
    def apply_state(self):
        pass


    #---------------------------------------------------------------------------
    def set_on(self):
        pass


    #---------------------------------------------------------------------------
    def set_off(self):
        pass


#===============================================================================
#===============================================================================

class Relay_Config(object):
    """
    A relay configuration groups multiple relays. These relays can even come
    from different relay boards
    """

    #---------------------------------------------------------------------------
    def __init__(self):
        self.relay_mgr_list = []


    #---------------------------------------------------------------------------
    def add_relay_mgr(self, relay):
        if relay is not None:
            manager = relay.get_manager()
            if manager is not None and manager not in self.relay_mgr_list:
                self.relay_mgr_list.append(manager)


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

    Operation mode 2: relays are driver vom I/O board power source
      remove the jumper between JD-VCC and VCC. Connect VCC to the I/O
      controller's I/O power and JD-VCC to the power source of the I/O controller
      board. Connect GND to the I/O controllers GND

    Operation mode 2: galvanic isolation of I/Os:
      remove jumper between VCC and JD-VCC. Connect JD-VCC and GND to a
      separate power source. Connect VCC to the I/O board's VCC


                  +-------------+
                  | optocoupler |
        o-- VCC --|...       ...|------- JD-VCC --o
                  | LED  =>  |  |           |
        o-- IO --+....       ...|---+    Relais --Transistor --- GND --o
                  |             |   |                  |
                  +-------------+   +------------------+
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
        # pulling an I/O down switched the relay on. We support 8 relays
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

