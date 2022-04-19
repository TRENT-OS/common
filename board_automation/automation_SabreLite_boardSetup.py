#!/usr/bin/python3

import os
import time
import pathlib

from . import relay_control
from . import sd_wire
from . import uart_reader
from . import wrapper_pyftdi


#===============================================================================
#===============================================================================

class Board_Setup():

    #---------------------------------------------------------------------------
    def __init__(self, printer = None):

        self.printer = printer

        pins = None

        if host_is_raspi:
            self.gpio = relay_control.RasPi_GPIO()
            pins = {'POWER': 4, 'RESET': 17, 'SW1_1': 27, 'SW1_2': 22}
        else:
            self.gpio = wrapper_pyftdi.get_pyftdi_gpio('ftdi://ftdi:232h:1/1')
            pins = {'POWER': 4, 'RESET': 5, 'SW1_1': 6, 'SW1_2': 7}

        relay_board = relay_control.Relay_Board(self.gpio)
        self.relay_config = relay_control.Relay_Config({
                                key: relay_board.get_relay(idx)
                                for key, idx in pins.items() }
                            })

        self.sd_wire = sd_wire.SD_Wire(
                    serial     = '202005170015',
                    usb_path   = '1-4.2.1.4.2.2',
                    mountpoint = '/media')


        self.uart0 = uart_reader.TTY_USB.find_device(
                        # FTDI 232 USB/Serial adapter
                        serial    = 'ftEGLPAR',
                        usb_path  = '1-4.2.1.4.3'
                     )

        self.uart1 = uart_reader.TTY_USB.find_device(
                        # FTDI 232 USB/Serial adapter
                        serial    = 'FTFMPNFD',
                        usb_path  = '1-4.2.1.4.4'
                     )

        self.log_monitor = uart_reader.UART_Reader(
                                device  = self.uart0.device,
                                name = 'UART0',
                                printer = self.printer)


    #---------------------------------------------------------------------------
    def cleanup(self):

        if self.gpio:
            self.gpio.close()

        if self.log_monitor:
            self.log_monitor.stop()

        if self.sd_wire:
            self.sd_wire.switch_to_host()
