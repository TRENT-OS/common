#!/usr/bin/python3

import time

from . import tools
from . import board_automation


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

class BoardRunner(board_automation.System_Runner):

    #---------------------------------------------------------------------------
    def __init__(self, run_context, board_setup):

        super().__init__(run_context, board_setup)

        self.board = Automation(
                        board_setup.relay_config,
                        run_context.printer)


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner, nothing special here
    # def do_cleanup(self):


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner
    def do_start(self):

        # make sure the board is powered off
        self.board.power_off()
        time.sleep(0.1)

        # setup the SD card
        mp = self.board_setup.sd_wire.switch_to_host_and_mount(timeout_sec = 5)

        self.print('content of {}'.format(mp))
        tools.print_files_from_folder(mp)

        self.board_setup.sd_wire.copy_file_to_card(self.run_context.system_image)

        self.board_setup.sd_wire.unmount_and_switch_to_device(timeout_sec = 5)

        # now the board is ready to boot, enable the UART logger and switch
        # the power on
        self.board_setup.log_monitor.start(
            log_file = self.system_log_file.name,
            print_log = self.run_context.print_log)

        time.sleep(0.1)

        self.board.power_on()


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner: nothing special here
    # def do_stop(self):


    #---------------------------------------------------------------------------
    # interface board_automation.System_Runner: ToDo: implement UART
    # def get_serial_socket(self):
