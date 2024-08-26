#!/usr/bin/python3

#
# Copyright (C) 2024, HENSOLDT Cyber GmbH
# 
# SPDX-License-Identifier: GPL-2.0-or-later
#
# For commercial licensing, contact: info.cyber@hensoldt.net
#

import time
import requests
import os
import pathlib
import shutil
import websocket

from collections import deque

from . import tools
from . import board_automation
from . import automation_HW_CI_boardSetup



ADDRESS      = "10.178.169.36"
PORT         = "8000"
URL          = f"http://{ADDRESS}:{PORT}"

#===============================================================================
#===============================================================================

class Automation():

    #---------------------------------------------------------------------------
    def __init__(self, printer = None, hw_platform= None):
        self.printer      = printer

        if hw_platform is None:
            raise Exception("Error: No hardware platform specified")
        
        self.device = hw_platform
        # put all relays in a well defined state


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    def __toggle_power(self, mode):
        if mode not in ["on", "off", "state"]:
            raise Exception(f"Error: Unknown mode {mode} selected for toggling board power")
        
        headers = {'accept': 'application/json'}
        full_url = f"{URL}/{self.device}/power/{mode}"
        return requests.post(full_url, headers=headers)

    #---------------------------------------------------------------------------
    def power_on(self):
        self.print(f'power on {self.device}')
        response = self.__toggle_power("on")
        if not response.ok:
            raise Exception(f"Error: Powering on device {self.device} failed: {response.status_code}: {response.text}")


    #---------------------------------------------------------------------------
    def power_off(self):
        self.print(f'power off {self.device}')
        response = self.__toggle_power("off")

        if not response.ok:
            raise Exception(f"Error: Powering on device {self.device} failed: {response.status_code}: {response.text}")


    #---------------------------------------------------------------------------
    def press_reset(self, delay = 0.1):
        self.print('reset')
        self.power_off()
        time.sleep(delay)
        self.power_on()
        pass


    #-------------------------------------------------------------------------------
    def check_board_power_status(self):
        response = self.__toggle_power("state")

        if not response.ok:
            raise Exception(f"Error: Powering on device {self.device} failed: {response.status_code}: {response.text}")

        self.print(f"Power state of {self.device}: {response.text}")
        return response.text == "auto-on"
        

#===============================================================================
#===============================================================================

class BoardRunner():

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner):
        self.generic_runner = generic_runner
        self.device = "-".join(self.generic_runner.run_context.platform.split("-")[:-1])
        printer = generic_runner.run_context.printer

        self.board_setup = automation_HW_CI_boardSetup.Board_Setup(printer, self.device, URL)
        self.board = Automation(printer, self.device)


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def cleanup(self):
        self.board_setup.cleanup()
        headers = {'accept': 'application/json'}
        full_url = f"{URL}/{self.device}/tftp/delete"
        requests.delete(full_url, headers=headers)
            

    #---------------------------------------------------------------------------
    def copy_tftp_boot_file(self):
        system_image = pathlib.Path("../../") / self.generic_runner.run_context.system_image
        if not os.path.exists(system_image):
            raise Exception(f"Error: system_image not found at: {self.generic_runner.run_context.system_image}")
        
        headers = {'accept': 'application/json'}
        full_url = f"{URL}/{self.device}/tftp/upload"
        file = {"file": open(system_image, "rb")}
        req = requests.post(full_url, headers=headers, files=file)
        if req.ok:
            return print(f"Success: System_image deployed")
        raise Exception(f"Error: Deployment of system image to proxy server failed with code {req.status_code}: {req.text}")
        
    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def start(self):

        # make sure the board if powered off
        self.board.power_off()
        time.sleep(0.1)

        # This starts the proxy only if it was explicitly enabled, otherwise it
        # does nothing.
        #self.generic_runner.startProxy(
        #    connection = f'UART:{self.self.board_setup.uart1.device}',
        #    enable_tap = True,
        #)

        # Copy system image to tftpboot directory
        self.copy_tftp_boot_file()

        # now the board is ready to boot, enable the UART logger and switch
        # the power on

        self.board_setup.log_monitor.start(
            log_file = self.generic_runner.system_log_file.name,
            print_log = self.generic_runner.run_context.print_log)
        time.sleep(0.1)

        self.board.power_on()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def stop(self):
        self.board.power_off()


    def __board_supports_data_uart(self):
        url = f'{URL}/{self.device}/data_uart/available'
        headers = { 'accept': 'application/json', }

        return requests.get(url, headers=headers).json()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def get_serial_socket(self):
        def socket_abstraction(url):
            ws = websocket.create_connection(url)
            # send data as 64 byte chunks with 10ms delay to not overburden uart/proxy
            ws.sendall = lambda data: [ (ws.send(data[i:i+64]), time.sleep(0.01)) for i in range(0, len(data), 64) ]
            ws.recv_orig, ws.recv = ws.recv, lambda _: ws.recv_orig().encode("utf-8") # convert to bytes to align with socket recv
            return ws

        if not self.__board_supports_data_uart():
            raise Exception('not implemented')
        
        url = f"ws://{ADDRESS}:{PORT}/{self.device}/data_uart/connect"
        return socket_abstraction(url)
    

#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
def get_BoardRunner(generic_runner):
    return BoardRunner(generic_runner)