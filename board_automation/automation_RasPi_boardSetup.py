#!/usr/bin/python3

#
# Copyright (C) 2020-2024, HENSOLDT Cyber GmbH
# 
# SPDX-License-Identifier: GPL-2.0-or-later
#
# For commercial licensing, contact: info.cyber@hensoldt.net
#

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

        self.gpio = wrapper_pyftdi.get_pyftdi_gpio('ftdi://ftdi:232h:1/1')
        relay_board = relay_control.Relay_Board(self.gpio)

        self.relay_config = relay_control.Relay_Config({
                                'POWER':  relay_board.get_relay(0),
                                'notRUN': relay_board.get_relay(1),
                                'notPEN': relay_control.Relay_Dummy()
                             })


        self.sd_wire = sd_wire.SD_Wire(
                    serial     = 'sdw-7',
                    usb_path   = '1-4.2.1.2.2.2',
                    mountpoint = '/media')


        self.uart0 = uart_reader.TTY_USB.find_device(
                        # use FTDI LC231X
                        serial    = 'FT43WXQB',
                        usb_path  = '1-4.2.1.2.1'
                     )

        self.log_monitor = uart_reader.UART_Reader(
                                device  = self.uart0.device,
                                name    = 'UART0',
                                printer = self.printer)


    #---------------------------------------------------------------------------
    def cleanup(self):

        if self.gpio:
            self.gpio.close()

        if self.log_monitor:
            self.log_monitor.stop()

        if self.sd_wire:
            self.sd_wire.switch_to_host()
