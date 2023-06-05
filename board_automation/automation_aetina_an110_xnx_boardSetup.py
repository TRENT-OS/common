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

        self.gpio = None
        # self.gpio = wrapper_pyftdi.get_pyftdi_gpio('ftdi://ftdi:232h:1/1')
        relay_board = None #relay_control.Relay_Board(self.gpio)

        self.relay_config = None
        # self.relay_config = relay_control.Relay_Config({
        #                         'POWER': relay_board.get_relay(4),
        #                         'RESET': relay_board.get_relay(5),
        #                         'SW1_1': relay_board.get_relay(6),
        #                         'SW1_2': relay_board.get_relay(7)
        #                     })

        self.sd_wire = None
        # self.sd_wire = sd_wire.SD_Wire(
        #             serial     = '202005170015',
        #             usb_path   = '1-4.2.1.4.2.2',
        #             mountpoint = '/media')


        self.uart0 = uart_reader.TTY_USB.find_device(
                         # FTDI 232 USB/Serial adapter
                         serial    = None,
                         usb_path  = '1-1.2'
                      )

        self.uart1 = uart_reader.TTY_USB.find_device(
                        # FTDI 232 USB/Serial adapter
                        serial    = None,
                        usb_path  = '1-1.3'
                     )

        print('serial_socket = ' + self.uart1.device)
        # print('serial_socket = ' + self.uart0.device)

        self.log_monitor = uart_reader.UART_Reader(
                                 device  = self.uart0.device,
                                 name = 'UART0',
                                 printer = self.printer)


    #---------------------------------------------------------------------------
    def cleanup(self):

        self.printer = None

        if self.gpio:
            self.gpio.close()

        if self.log_monitor:
            self.log_monitor.stop()

        if self.sd_wire:
            self.sd_wire.switch_to_host()
