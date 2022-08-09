#!/usr/bin/python3

import sys
import traceback
import os
import signal
import shutil
import subprocess
import time
import datetime

from . import tools


#---------------------------------------------------------------------------
def execute_os_cmd(
        cmd_arr,
        stdout = subprocess.PIPE,
        stderr = subprocess.STDOUT,
        env = None):

    # ret = os.system(cmd)
    # if (0 != ret):
    #     print('ERROR: ret={} for: {}'.format(ret, cmd_arr))
    # return ret

    p = subprocess.Popen(
            cmd_arr,
            env = env,
            stdout = stdout,
            stderr = subprocess.STDOUT)

    while(True):
        # ToDo: we need a readline() with timeout to avoid blocking here
        line = p.stdout.readline()
        if line:
            line = line.decode('utf-8').strip()
            print('[{}] {}'.format(cmd_arr[0], line))

        else:
            ret = p.poll()
            if ret is not None:
                if (0 != ret):
                    print('ERROR: ret={} for: {}'.format(ret, cmd_arr))

                return ret


#===============================================================================
#===============================================================================

class install_abort_handler():

    #---------------------------------------------------------------------------
    def __init__(self, cleanup_handler):
        self.cleanup_handler = cleanup_handler
        signal.signal(signal.SIGINT, self.signal_handler)


    #---------------------------------------------------------------------------
    def signal_handler(self, sig, frame):
        print('... caught abort')

        if self.cleanup_handler:
            self.cleanup_handler()

        sys.exit(0)


#===============================================================================
#===============================================================================

class ProcessWrapper:

    #---------------------------------------------------------------------------
    def __init__(
        self,
        cmd_arr,
        log_file_stdout = None,
        log_file_stderr = None,
        printer = None,
        name = None
    ):

        self.cmd_arr = cmd_arr
        self.name = self.cmd_arr[0] if name is None else name

        self.printer = printer if printer else tools.PrintSerializer()
        self.process = None

        self.log_file_stdout = log_file_stdout
        self.thread_stdout   = None

        self.log_file_stderr = log_file_stderr
        self.thread_sterr    = None


    #---------------------------------------------------------------------------
    # sub-classes may extend this
    def print(self, msg):
        if self.printer:
            self.printer.print(msg)


    #---------------------------------------------------------------------------
    def is_running(self):
        try:

            p = self.process
            return (p is not None) and (p.poll() is None)

        except Exception as e:

            exc_info = sys.exc_info()
            self.print('Exception in is_running() for {}: {}'.format(self, e))
            traceback.print_exception(*exc_info)

        return False


    #---------------------------------------------------------------------------
    def start(
        self,
        has_stdin = False,
        env = None,
        print_log = False):

        # process must not be running
        assert(self.process is None)

        self.process = subprocess.Popen(
                            self.cmd_arr,
                            env = None,
                            stdin = subprocess.PIPE if has_stdin else None,
                            stdout = subprocess.PIPE if (print_log or (self.log_file_stdout is not None)) \
                                     else None,
                            stderr = subprocess.PIPE if (print_log or (self.log_file_stderr is not None)) \
                                     else None
                       )

        # Wrapper function for the actual monitoring. It is running in a daemon
        # thread that gets terminated automatically when the main thread dies.
        def monitor_channel_loop(
            process_wrapper,
            h_stream,
            name,
            printer = None,
            logfile_name = None):

            assert(process_wrapper)
            assert(h_stream)

            t_start = datetime.datetime.now()
            while (process_wrapper.is_running()):

                # Block reading a line. Seems in some cases readline() can run into
                # a timeout and return nothing. Or maybe the process has termiated.
                line = h_stream.readline()
                if (len(line) == 0):
                    continue

                line_str = line.decode('utf-8')
                line_str = line_str.replace('\b', '<BACKSPACE>')

                delta = datetime.datetime.now() - t_start;
                # timestamp = datetime.datetime(delta.total_seconds()).strftime("%H%:M:%S.%f")
                # msg = '[{} {}] {}'.format(timestamp[:-3], name, line_str)

                # Log to the printer fist, as this is expected to work without
                # issues.
                if printer:
                    printer.print(f'[{delta} {name}] {line_str}')

                # Log to a file. This might into an error in the worst case, so
                # this could be improved with some exception catching one day.
                if logfile_name:
                    with open(logfile_name, "a") as f:
                        f.write(f'[{delta}] {line_str}{os.linesep}')
                        f.flush() # ensure things are really written


        if self.process.stdout:
            tools.run_in_thread(
                lambda thread: monitor_channel_loop(
                    self,
                    self.process.stdout,
                    f'{self.name}/stdout',
                    self.printer if (print_log) else None,
                    self.log_file_stdout
                )
            )

        if self.process.stderr:
            tools.run_in_thread(
                lambda thread: monitor_channel_loop(
                    self,
                    self.process.stderr,
                    f'{self.name}/stderr',
                    self.printer if (print_log) else None,
                    self.log_file_stderr
                )
            )

        # set up a termination handler, that does the internal cleanup. This
        # is needed when e.g. our parent process is aborted and thus all child
        # processes are terminated. We need to ensure all our monitoring
        # threads also terminate.
        tools.run_in_thread(
            lambda thread:
            self.process.wait() and self.terminate()
        )


    #---------------------------------------------------------------------------
    def terminate(self):
        p = self.process
        if p is not None:
            p.terminate()
            self.process = None
