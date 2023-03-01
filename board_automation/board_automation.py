#!/usr/bin/python3

import sys
import os
import time

from . import tools
from . import process_tools
from enum import Enum

#===============================================================================
#===============================================================================

class BootMode(Enum):
    BARE_METAL  = 1
    SEL4_NATIVE = 2
    SEL4_CAMKES = 3


#===============================================================================
#===============================================================================

class Run_Context():

    #---------------------------------------------------------------------------
    def __init__(
        self,
        log_dir,
        resource_dir,
        platform,
        system_image,
        sd_card_size,
        printer           = None,
        print_log         = False,
        boot_mode         = BootMode.BARE_METAL,
        proxy_config      = None,
        additional_params = None):

        self.log_dir           = log_dir
        self.resource_dir      = resource_dir
        self.platform          = platform
        self.system_image      = system_image
        self.sd_card_size      = sd_card_size
        self.printer           = printer
        self.print_log         = print_log
        self.boot_mode         = boot_mode
        self.proxy_config      = proxy_config
        self.additional_params = additional_params


#===============================================================================
#===============================================================================

class System_Runner():

    #---------------------------------------------------------------------------
    def __init__(self, run_context):

        if run_context.system_image is None:
            raise Exception('ERROR: no system image given')

        if not os.path.isfile(run_context.system_image):
            raise Exception(f'ERROR: missing system image: {run_context.system_image}')

        self.run_context  = run_context
        self.board_runner = None

        process_tools.install_abort_handler(self.cleanup)

        self.system_log_file = None

        sys_log_file_fqn = self.get_log_file_fqn('guest_out.txt')
        if sys_log_file_fqn:
            self.system_log_file = tools.Log_File(sys_log_file_fqn)
            self.print(f'  test system log: {self.system_log_file.name}')


    #---------------------------------------------------------------------------
    def set_board_runner(self, board_runner):
        if self.board_runner is not None:
            raise Exception(f'board runner already set: {self.board_runner}')

        self.board_runner = board_runner


    #---------------------------------------------------------------------------
    def print(self, msg):
        if self.run_context.printer:
            self.run_context.printer.print(msg)


    #---------------------------------------------------------------------------
    def cleanup(self):
        if self.board_runner is not None:
               self.board_runner.cleanup()


    #---------------------------------------------------------------------------
    def start(self):

        if self.board_runner is None:
            raise Exception('no board specific runner set')

        self.board_runner.start()

        if self.run_context.boot_mode == BootMode.BARE_METAL:
            return

        (ret, idx, idx2) = self.system_log_match_multiple_sequences([
            # system has started, check that the ELF Loader started properly.
            # This can take some time depending on the board's boot process
            ( [ 'ELF-loader started' ], 10 ),

            # give the ELF Loader 10 seconds to unpack the system. Some
            # platforms print "Jumping to kernel-image entry point..." when
            # ELF loader is done, but some don't. So all we can do is wait for
            # some kernel message here.
            ( [ 'Bootstrapping kernel' ], 10 ),

            # check if the seL4 kernel booted properly, 5 secs should be enough
            ( [ 'Booting all finished, dropped to user space' ], 5),
        ])

        if not ret:
            raise Exception(f'boot string #{idx}.{idx2} not found')

        # There is no CapDL loader in a native system.
        if self.run_context.boot_mode == BootMode.SEL4_NATIVE:
            return

        (ret, idx, idx2) = self.system_log_match_multiple_sequences([

            # the CapDL Loader runs a as root task. It should run immediately,
            # so 2 secs should do.
            ( [ 'Starting CapDL Loader...' ], 2),

            # it takes some time for the CapDL Loader to set up the system,
            # especially if there is a lot of output on the UART, where the
            # baudrate setting slows things down. So let's give it 20 seconds.
            ( [ 'CapDL Loader done, suspending...' ], 20),
        ])

        if not ret:
            raise Exception(f'CapDL Loader string #{idx}.{idx2} not found')


    #---------------------------------------------------------------------------
    def stop(self):
        err = None
        if self.board_runner is not None:
            try:
               self.board_runner.stop()
            except Exception as e:
                print(f'board runner stop exception: {e}')
                err = e

        self.cleanup()

        if err is not None:
            raise Exception(f'board cleanup failed: {err}')


    #---------------------------------------------------------------------------
    def get_serial_socket(self):
        return self.board_runner.get_serial_socket()


    #---------------------------------------------------------------------------
    # get log file fully qualified name
    def get_log_file_fqn(self, name):

        log_dir = self.run_context.log_dir

        if log_dir is None:
            return None

        if not os.path.isdir(log_dir):
            raise Exception(f'log directory missing: {log_dir}')

        return os.path.join(log_dir, name)


    #---------------------------------------------------------------------------
    def get_system_log(self):
        return self.system_log_file.open_non_blocking()


    #---------------------------------------------------------------------------
    def system_log_match_sequence(self, str_arr, timeout_sec = 0):
        return self.system_log_file.match_sequence(
                    str_arr,
                    tools.Timeout_Checker(timeout_sec))


    #---------------------------------------------------------------------------
    def system_log_match_multiple_sequences(self, seq_arr):
        return self.system_log_file.match_multiple_sequences(seq_arr)
