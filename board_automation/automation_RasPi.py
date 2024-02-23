#!/usr/bin/python3

#
# Copyright (C) 2020-2024, HENSOLDT Cyber GmbH
# 
# SPDX-License-Identifier: GPL-2.0-or-later
#
# For commercial licensing, contact: info.cyber@hensoldt.net
#

import time

from . import tools
from . import board_automation
from . import automation_RasPi_boardSetup


#===============================================================================
#===============================================================================

class Automation():

    #---------------------------------------------------------------------------
    def __init__(self, relay_config, printer = None):

        req_relays = ['POWER', 'notRUN', 'notPEN']
        if not relay_config.check_relays_exist(req_relays):
            raise Exception(
                    'relay configuration invalid, need {}'.format(req_relays))

        self.relay_config = relay_config;
        self.printer      = printer

        # put all relays in a well defined state
        self.relay_config.set_all_off()


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    #---------------------------------------------------------------------------
    def power_on(self):
        self.print('power on')
        self.relay_config.POWER.prepare_state_on()
        self.relay_config.notRUN.prepare_state_off()
        self.relay_config.notPEN.prepare_state_off()
        self.relay_config.apply_state()


    #---------------------------------------------------------------------------
    def power_off(self):
        self.print('power off')
        self.relay_config.POWER.set_off()


    #---------------------------------------------------------------------------
    def power_disable(self):
        self.print('power disable')
        self.relay_config.notPEN.set_on()


    #---------------------------------------------------------------------------
    def reset(self, delay = 0.1):
        self.print('reset')
        self.relay_config.notRUN.set_on()
        time.sleep(delay)
        self.relay_config.notRUN.set_off()


#===============================================================================
#===============================================================================

class BoardRunner():

    #---------------------------------------------------------------------------
    def __init__(self, generic_runner):
        self.generic_runner = generic_runner
        printer = generic_runner.run_context.printer
        self.board_setup = Board_Setup(printer)
        self.board = Automation(self.board_setup.relay_config, printer)


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def cleanup(self):
        self.board_setup.cleanup()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def start(self):

        # make sure the board is powered off
        self.board.power_off()
        time.sleep(0.1)

        # This starts the proxy only if it was explicitly enabled, otherwise it
        # does nothing.
        #self.generic_runner.startProxy(
        #    connection = f'UART:...',
        #    enable_tap = True,
        #)

        # setup the SD card
        mp = self.board_setup.sd_wire.switch_to_host_and_mount(timeout_sec = 5)

        self.print('content of {}'.format(mp))
        tools.print_files_from_folder(mp)

        self.board_setup.sd_wire.copy_file_to_card(self.generic_runner.run_context.system_image)

        self.board_setup.sd_wire.unmount_and_switch_to_device(timeout_sec = 5)

        # now the board is ready to boot, enable the UART logger and switch
        # the power on
        self.board_setup.log_monitor.start(
            log_file = self.generic_runner.run_context.system_log_file.name,
            print_log = self.generic_runner.run_context.print_log)

        time.sleep(0.1)

        self.board.power_on()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def stop(self):
        self.board.power_off()


    #---------------------------------------------------------------------------
    # called by generic_runner (board_automation.System_Runner)
    def get_serial_socket(self):
        raise Exception('not implemented')


#===============================================================================
#===============================================================================

#-------------------------------------------------------------------------------
def get_BoardRunner(generic_runner):
    return BoardRunner(generic_runner)
