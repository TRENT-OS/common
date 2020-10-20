#!/usr/bin/python3

import sys
import os
import time

from . import tools
from . import process_tools

#===============================================================================
#===============================================================================

class Run_Context(object):

    #---------------------------------------------------------------------------
    def __init__(
        self,
        log_dir,
        platform,
        system_image,
        sd_card_size,
        printer = None,
        print_log = False):

        self.log_dir      = log_dir
        self.platform     = platform
        self.system_image = system_image
        self.sd_card_size = sd_card_size
        self.printer      = printer
        self.print_log    = print_log


#===============================================================================
#===============================================================================

class System_Runner(object):

    #---------------------------------------------------------------------------
    def __init__(self, run_context, board_setup = None):

        if run_context.system_image is None:
            raise Exception('ERROR: no system image given')

        if not os.path.isfile(run_context.system_image):
            raise Exception('ERROR: missing system image: {}'.format(
                    run_context.system_image))


        self.run_context  = run_context
        self.board_setup  = board_setup

        process_tools.install_abort_handler(self.cleanup)

        self.system_log_file = None

        sys_log_file_fqn = self.get_log_file_fqn('guest_out.txt')
        if sys_log_file_fqn:
            self.system_log_file = tools.Log_File(sys_log_file_fqn)

            self.print('  test system log: {}'.format(
                self.system_log_file.name))


    #---------------------------------------------------------------------------
    # sub-classes shall not overwrite this
    def cleanup(self):
        if self.board_setup:
            self.board_setup.cleanup()

        self.do_cleanup()


    #---------------------------------------------------------------------------
    # sub-classes may extend this
    def print(self, msg):
        if self.run_context.printer:
            self.run_context.printer.print(msg)


    #---------------------------------------------------------------------------
    # sub-classes shall not overwrite this
    def start(self, print_log = None):
        if print_log is None:
            print_log = self.run_context.print_log

        self.do_start(print_log)


    #---------------------------------------------------------------------------
    # sub-classes shall not overwrite this
    def stop(self):
        try:
            self.do_stop()
        finally:
            self.cleanup()


    #---------------------------------------------------------------------------
    # sub-classes must implement this
    def do_start(self, print_log):
        raise Exception('implement me')


    #---------------------------------------------------------------------------
    # sub-classes may implement this
    def do_stop(self):
        pass

    #---------------------------------------------------------------------------
    # sub-classes may implement this
    def do_cleanup(self):
        pass


    #---------------------------------------------------------------------------
    # sub-classes may overwrite this
    def check_start_success(self):

        (ret , idx, idx2) = self.system_log_match_multiple_sequences([

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

            # the CapDL Loader runs a as root task. It should run immediately,
            # so 2 secs should do.
            ( [ 'Starting CapDL Loader...' ], 2),

            # it takes some time for the CapDL Loader to set up the system,
            # especially if there is a lot of output on the UART, where the
            # baudrate setting slows things down. So let's give it 20 seconds.
            ( [ 'CapDL Loader done, suspending...' ], 20),
        ])

        if not ret:
            raise Exception('boot string #{}.{} not found'.format(idx, idx2))


    #---------------------------------------------------------------------------
    # sub-classes may overwrite this if they provide a socket
    def get_serial_socket(self):
        return None


    #---------------------------------------------------------------------------
    # get log file fully qualified name
    def get_log_file_fqn(self, name):

        log_dir = self.run_context.log_dir

        if log_dir is None:
            return None

        if not os.path.isdir(log_dir):
            raise Exception('log directory missing: {}'.format(log_dir))

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
