#!/usr/bin/python3

#
# Copyright (C) 2024, HENSOLDT Cyber GmbH
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
    def __init__(self, printer = None, hw_platform= None, url=None):

        self.printer = printer

        if hw_platform is None:
            raise Exception("Error: No hardware platform specified")
        self.device = hw_platform

        if url is None:
            raise Exception("Error: no uart proxy url specified")
        self.url = url

        self.printer.print(f"Connecting to uart_proxy api at: {self.url}/{self.device}/*")
        
        self.log_monitor = uart_reader.UART_Proxy_Reader(
                self.device,
                self.url,
                printer=self.printer
        )

    #---------------------------------------------------------------------------
    def cleanup(self):
        if self.log_monitor:
            self.log_monitor.stop()
