#!/usr/bin/python3

#
# Copyright (C) 2020-2024, HENSOLDT Cyber GmbH
# 
# SPDX-License-Identifier: GPL-2.0-or-later
#
# For commercial licensing, contact: info.cyber@hensoldt.net
#

import sys
import os
import pathlib
import time

from . import tools
from . import process_tools
from . import wrapper_proxy
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
        request,
        boot_mode         = BootMode.BARE_METAL,
        use_proxy         = False,
        sd_card_size      = None,
        additional_params = None
    ):

        self.request = request
        opts = request.config.option

        self.boot_mode = boot_mode

        # ToDo: This is another hack to pass more parameters. Clarify what this
        #       is used for and consider adding dedicated field then.
        self.additional_params = additional_params

        self.printer = tools.PrintSerializer()
        self.print_log = opts.print_logs

        log_dir = pathlib.Path(request.node.name).stem
        if (opts.log_dir is not None):
            log_dir = os.path.join(opts.log_dir, log_dir)
        self.log_dir = log_dir

        self.resource_dir      = opts.resource_dir
        self.platform          = opts.target
        self.system_image      = opts.system_image

        self.sd_card_size      = sd_card_size if sd_card_size is not None \
                                 else int(opts.sd_card) if opts.sd_card \
                                 else 0

        if use_proxy and not opts.proxy:
            raise Exception('ERROR: missing proxy config')
        self.use_proxy         = use_proxy
        self.proxy_binary      = opts.proxy if use_proxy else None



#===============================================================================
#===============================================================================

class BootChecker:

    #---------------------------------------------------------------------------
    @staticmethod
    def check_sel4(log):
        ret = log.find_matches_in_lines([
            # system has started, check that the ELF Loader started properly.
            # This can take some time depending on the board's boot process
            ('ELF-loader started', 60),
            # give the ELF Loader 10 seconds to unpack the system. Some
            # platforms print "Jumping to kernel-image entry point..." when
            # ELF loader is done, but some don't. So all we can do is wait for
            # some kernel message here.
            ('Bootstrapping kernel', 30),
            # check if the seL4 kernel booted properly, 5 secs should be enough
            ('Booting all finished, dropped to user space', 5),
        ])
        if not ret.ok:
            raise Exception(f'sel4 boot string #{len(ret.items)-1} not found: {ret.get_missing()}')


    #---------------------------------------------------------------------------
    @staticmethod
    def check_capdl_loader(log):
        ret = log.find_matches_in_lines([
            # the CapDL Loader runs a as root task. It should run immediately,
            # so 2 secs should do.
            ('Starting CapDL Loader...' , 2),
            # it takes some time for the CapDL Loader to set up the system,
            # especially if there is a lot of output on the UART, where the
            # baudrate setting slows things down. So let's give it 20 seconds.
            ('CapDL Loader done, suspending...', 60),
        ])
        if not ret.ok:
            raise Exception(f'CapDL Loader string #{len(ret.items)-1} not found: {ret.get_missing()}')


#===============================================================================
#===============================================================================

class System_Runner():

    #---------------------------------------------------------------------------
    def __init__(self, run_context):

        if run_context.system_image is None:
            raise Exception('ERROR: no system image given')

        if not os.path.isfile(pathlib.Path("../..") / run_context.system_image):
            raise Exception(f'ERROR: missing system image: {run_context.system_image}')

        self.run_context  = run_context

        process_tools.install_abort_handler(self.cleanup)

        self.board_runner = None

        # Create the proxy wrapper only of we are going to use the Proxy.
        self.proxy = None if not self.run_context.use_proxy \
                     else wrapper_proxy.Proxy(
                            binary  = self.run_context.proxy_binary,
                            printer = run_context.printer,
                          )

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
    def is_proxy_running(self):
        return (self.proxy is not None) and self.proxy.is_running()


    #---------------------------------------------------------------------------
    # This is a callback that the actual board_runner can use in its start() to
    # start the proxy with a specific configuration. As a convenience, it may
    # call this unconditionally, we just do nothing if the proxy usage was not
    # enabled explicitly.
    def startProxy(self, connection, enable_tap, print_log = False):
        if self.proxy:
            assert not self.is_proxy_running()
            self.proxy.start(
                log_dir = self.run_context.log_dir,
                connection = connection,
                enable_tap = enable_tap,
                print_log  = print_log,
            )


    #---------------------------------------------------------------------------
    def start(self):

        if self.board_runner is None:
            raise Exception('no board specific runner set')

        try:
            # This may call startProxy()
            self.board_runner.start()
        except:
            print('flush log after board boot failure')
            time.sleep(1)
            self.get_system_log_line_reader().flush()
            raise

        if self.run_context.boot_mode == BootMode.BARE_METAL:
            return

        # The initial boot output of a bare-metal system is fully custom, this
        # should be handled by the board specific code. Ideally, we'd get a
        # log reader now, that has consumed all specific log, so we just see
        # the ElfLoader starting seL4. This could be achieved with a new API
        # like "log = self.board_runner.log". For now, we get the whole log
        # and just hope there are no accidental collisions with similar
        # messages.
        log = self.get_system_log_line_reader()

        BootChecker.check_sel4(log)


        if self.run_context.boot_mode == BootMode.SEL4_NATIVE:
            return

        BootChecker.check_capdl_loader(log)

        if self.run_context.boot_mode == BootMode.SEL4_CAMKES:
            return

        raise Exception(f'unsupported boot mode: #{self.run_context.boot_mode}')


    #---------------------------------------------------------------------------
    def stop(self):

        # ToDo: Log checking and log printing are separate threads, where the
        #       checker thread is usually "faster" than the printer thread.
        #       Having a short short delay here is a hack to ensure all logs are
        #       is printed. Increase  the value, if some logs are still missing.
        #       A proper fix shgould synchronize the threads somehow, so at
        #       least everything that was checked is also printed. A delay in
        #       the end might still be needed, as there could be additional log
        #       output that if worth showing.
        time.sleep(0.2)
        self.get_system_log_line_reader().flush()

        if self.proxy:
            self.proxy.stop()

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
    # Returns an iterator that yields the lines of the file until the timeout
    # is reached. By default the timeout is infinite.
    def get_system_log_line_reader(self, timeout = None):
        return self.system_log_file.get_line_reader(timeout)


    #-------------------------------------------------------------------------------
    # This is a convenience function.
    def system_log_match(self, match_obj):
        log = self.get_system_log_line_reader()
        return log.find_matches_in_lines(match_obj)


    #---------------------------------------------------------------------------
    # This function is a candidate for deprecation, as there are only few cases
    # where the raw non-blocking handle it needed. Furthermore, this uses an
    # infinite timeout by default, so it may block forever if the log file is
    # not created due to a early failure when trying to start a board. For many
    # use cases, the function get_system_log_line_reader() seems a much better
    # choice, because the returned reader can then be used to iterate over the
    # lines. It can also provide the (non-blocking) handle, if this is really
    # needed.
    def get_system_log(self, timeout = None):
        return self.system_log_file.open_non_blocking(timeout)


    #---------------------------------------------------------------------------
    # This function is DEPRECATED. The generic string matching API from the line
    # reader provided by get_system_log_line_reader() is much more flexible.
    def system_log_match_sequence(self, str_arr, timeout_sec = 0):
        log = self.get_system_log_line_reader(timeout_sec)
        for idx, string in enumerate(str_arr):
            assert isinstance(string, str)
            for line in log:
                if string in line:
                    break
            else:  # no break means timeout before we could find a match
                return (False, idx)
        # If we arrive here, all string could be matched
        return (True, None)


    #---------------------------------------------------------------------------
    # This function is DEPRECATED. The generic string matching API from the line
    # reader provided by get_system_log_line_reader() is much more flexible.
    def system_log_match_multiple_sequences(self, seq_arr):
        log = self.get_system_log_line_reader()
        for idx, (str_arr, timeout_sec) in enumerate(seq_arr):
            log.set_timeout(timeout_sec)
            for idx2, string in enumerate(str_arr):
                assert isinstance(string, str)
                for line in log:
                    if string in line:
                        break
                else: # no break means timeout before we could find a match
                    return (False, idx, idx2)
        # If we arrive here, all string could be matched
        return (True, None, None)
