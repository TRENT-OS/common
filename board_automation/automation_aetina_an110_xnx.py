#!/usr/bin/python3

#
# Copyright (C) 2023-2024, HENSOLDT Cyber GmbH
# 
# SPDX-License-Identifier: GPL-2.0-or-later
#
# For commercial licensing, contact: info.cyber@hensoldt.net
#

import time

from . import tools
from . import board_automation
from . import automation_aetina_an110_xnx_boardSetup

from . import process_tools
import serial
import os


#===============================================================================
#===============================================================================

class Automation():

    #---------------------------------------------------------------------------
    def __init__(self, relay_config, printer = None):

        # req_relays = ['POWER', 'RESET', 'SW1_1', 'SW1_2']
        # if not relay_config.check_relays_exist(req_relays):
        #     raise Exception(
        #             'relay configuration invalid, need {}'.format(req_relays))

        self.relay_config = None
        self.printer      = printer


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    #---------------------------------------------------------------------------
    def power_off(self):
        self.print('power off')
        # self.relay_config.POWER.set_off()

#===============================================================================
#===============================================================================

class SerialWrapper(serial.Serial):

    def sendall(self, data):
        return self.write(data)

#===============================================================================
#===============================================================================

class BoardRunner():

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner):
        self.generic_runner = generic_runner
        printer = generic_runner.run_context.printer
        self.board_setup = automation_aetina_an110_xnx_boardSetup.Board_Setup(printer)
        self.board = Automation(self.board_setup.relay_config, printer)

        self.process_proxy = None
        self.port = None


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def cleanup(self):
        self.board_setup.cleanup()
        if self.is_proxy_running():
            self.process_proxy.terminate()
            self.proxy_process = None


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def start(self):

        time.sleep(0.1)
        # now the board is ready to boot, enable the UART logger and switch
        # the power on

        log_file = self.generic_runner.system_log_file.name
        print_log = self.generic_runner.run_context.print_log


        self.board_setup.log_monitor.start(
            log_file,
            print_log)

        if self.generic_runner.run_context.use_proxy:
            uart = self.board_setup.uart1
            self.generic_runner.startProxy(
                connection = f'UART:{uart.device}',
                enable_tap = True,
            )

        # if self.proxy_cfg_str:
        #     self.start_proxy(print_log)

        print("Start Board")
        time.sleep(2)


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def stop(self):
        self.board.power_off()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def get_serial_socket(self):
        return self.board_setup.uart1


    #---------------------------------------------------------------------------
    def is_proxy_running(self):
        return self.process_proxy and self.process_proxy.is_running()


    #---------------------------------------------------------------------------
    def get_printer(self):
        if not self.generic_runner.run_context:
            return None

        return self.generic_runner.run_context.printer


    #---------------------------------------------------------------------------
    def print(self, msg):
        printer = self.get_printer()
        if printer:
            printer.print(msg)


    #---------------------------------------------------------------------------
    def start_proxy(self, print_log):

        assert(not self.is_proxy_running())
        # assert( self.proxy_cfg_str)
        assert isinstance(self.generic_runner.run_context.proxy_config, str)

        print("Start Proxy")
        arr = self.generic_runner.run_context.proxy_config.split(',')
        proxy_app = arr[0]
        serial_board_connection = 'UART'
        #serial_board_connection = arr[1] if (1 != len(arr)) else 'PTY'

        assert(proxy_app is not None)
        if not os.path.isfile(proxy_app):
            raise Exception(f'ERROR: missing proxy app: {proxy_app}')

        if(serial_board_connection != 'UART'):
            raise Exception(
                f'ERRROR: invalide Proxy/Board connection mode: {serial_board_connection}')

        if self.board_setup.uart1 is None:
            raise Exception(
                f'ERROR: Could not find proxy tty device')

        # Start the proxy and have it connect to bridge
        cmd_arr = [
                proxy_app,
                '-c', f'UART:{self.board_setup.uart1.device}',
                '-t', '1' #enable TAP
                ]

        self.process_proxy = process_tools.ProcessWrapper(
                                cmd_arr,
                                log_file_stdout = self.generic_runner.get_log_file_fqn('proxy_out.txt'),
                                log_file_stderr = self.generic_runner.get_log_file_fqn('proxy_err.txt'),
                                printer = self.get_printer(),
                                name = 'Proxy'
                            )

        self.print(f'starting Proxy: {" ".join(cmd_arr)}')
        self.print(f'  proxy stdout: {self.process_proxy.log_file_stdout}')
        self.print(f'  proxy stderr: {self.process_proxy.log_file_stderr}')

        self.process_proxy.start(print_log)


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner, ToDo: implement UART
    def get_serial_socket(self):
        # if(self.proxy_cfg_str):
        #     raise Exception('ERROR: Proxy is already configured to use UART1!')
        if(self.port is None):
            tty_usb = self.board_setup.uart1
            self.port = SerialWrapper(tty_usb.device, 115200, timeout=1)
        return self.port

#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
def get_BoardRunner(generic_runner):
    return BoardRunner(generic_runner)