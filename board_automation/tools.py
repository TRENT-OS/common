#!/usr/bin/python3

import os
import fcntl
import threading
import time
import datetime

import logs


#-------------------------------------------------------------------------------
def get_remaining_timeout_or_zero(time_end):
        time_now = time.time()
        return 0 if (time_now >= time_end) \
               else time_end - time_now


#===============================================================================
#===============================================================================

class Timeout_Checker(object):

    #---------------------------------------------------------------------------
    # any value less than 0 means infinite
    def __init__(self, timeout_sec):

        self.timeout_sec = timeout_sec

        self.time_end = time.time()
        if (timeout_sec > 0):
            self.time_end += timeout_sec


    #---------------------------------------------------------------------------
    def is_infinite(self):
        return (self.timeout_sec < 0)

    #---------------------------------------------------------------------------
    def get_remaining(self):
        return -1 if self.is_infinite() \
               else get_remaining_timeout_or_zero(self.time_end)

    #---------------------------------------------------------------------------
    def has_expired(self):
        # remaining time is -1 for infinite, 0 if expired and a value greater
        # zero otherwise. So checking for 0 does the job nicely
        return 0 == self.get_remaining()


    #---------------------------------------------------------------------------
    def sleep(self, timeout):
        assert( timeout > 0 )

        if not self.is_infinite():

            timeout_remining = get_remaining_timeout_or_zero(self.time_end)

            # don't sleep at all if there is no time left
            if (0 == timeout_remining):
                return

            timeout = min(timeout, timeout_remining)

        time.sleep(timeout)


#===============================================================================
#===============================================================================

class Log_File(object):

    #---------------------------------------------------------------------------
    def __init__(self, name):
        self.name = name


    #---------------------------------------------------------------------------
    # if the file does not exist, keep checking every 100 ms until the timeout
    # has expired or the checker function says we can stop
    def open_non_blocking(
            self,
            newline = None,
            mode = 'r',
            timeout_sec = 0,
            checker_func = None ):

        timeout = Timeout_Checker(timeout_sec)

        while True:

            if os.path.isfile(self.name):

                f = open(self.name, mode, newline=newline)
                if f:
                    fd = f.fileno()
                    flag = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)

                return f

            if timeout.has_expired():
                return None

            if checker_func and not checker_func():
                return None

            timeout.sleep(0.1)


    #---------------------------------------------------------------------------
    def start_monitor(self, printer, checker_func = None):

        def monitoring_thread():

            start = datetime.datetime.now()

            f_log = self.open_non_blocking(
                        timeout_sec = -1,
                        checker_func = checker_func )

            if not f_log:
                printer.print(
                    '[{}] monitor terminated, could not open: {}'.format(
                        self,
                        self.name))
                return

            with f_log:
                is_abort = False
                while True:
                    # readline() return a string terminated by "\n" for every
                    # complete line. On timeout (ie. EOF reached), there is no
                    # terminating "\n"
                    #
                    # There is a line break bug in some logs, where "\n\r" is
                    # used instead of "\r\n". Universal newline handling only
                    # accepts "\r", "\n" and "\r\n" as line break, so this is
                    # taken as two line breaks and we see a lot of empty lines.
                    line = ""
                    while True:
                        line += f_log.readline()

                        if line.endswith("\n"):
                            line = line.strip()
                            break

                        if checker_func and not checker_func():
                            # printer.print('[{}] checker reported abort'.format(self))
                            is_abort = True
                            break;

                        time.sleep(0.1)

                    if line:
                        delta = datetime.datetime.now() - start;
                        printer.print('[{}] {}'.format(delta, line.strip()))

                    if is_abort:
                        #printer.print('[{}] monitor terminated for {}'.format(self, self.name))
                        return


        threading.Thread(
            target = monitoring_thread,
            args = ()
        ).start()


    #---------------------------------------------------------------------------
    def match_multiple_sequences(self, seq_arr):

        (expr_array, timeout_sec) = seq_arr[0]
        hLog = self.open_non_blocking(timeout_sec = timeout_sec)
        if not hLog:
            raise Exception('multi-sequence matching failed, could not open: {}'.format(self.name))

        with hLog:
            (ret, text, expr_fail, idx) = logs.check_log_match_multiple_sequences(
                                            hLog,
                                            seq_arr)

            if (not ret):
                raise Exception('missing in sequence #{}: {}'.format(idx, expr_fail))


    #---------------------------------------------------------------------------
    def match_sequence(self, str_arr, timeout_sec = 0, no_exception = False):

        timeout = Timeout_Checker(timeout_sec)
        hLog = self.open_non_blocking(timeout_sec = timeout.getRemaining())
        if not hLog:
            raise Exception('sequence matching failed, could not open: {}'.format(self.name))

        with hLog:
            (ret, text, expr_fail) = logs.check_log_match_sequence(
                                        hLog,
                                        str_arr,
                                        timeout_sec = timeout.getRemaining())

            if (not ret):
                raise Exception('missing in sequence: {}'.format(expr_fail))


    #---------------------------------------------------------------------------
    def match_set(self, str_arr, timeout_sec = 0):

        timeout = Timeout_Checker(timeout_sec)
        hLog = self.open_non_blocking(timeout_sec = timeout.getRemaining())
        if not hLog:
            raise Exception('set matching failed, could not open: {}'.format(self.name))

        timeout = Timeout_Checker(timeout_sec)

        with hLog:
            (ret, text, expr_fail) = logs.check_log_match_set(
                                        hLog,
                                        str_arr,
                                        timeout_sec = timeout.getRemaining())

            if (not ret):
                raise Exception('missing in set: {}'.format(expr_fail))
