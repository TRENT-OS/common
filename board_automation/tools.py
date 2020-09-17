#!/usr/bin/python3

import os
import fcntl
import threading
import time
import datetime
import re


#-------------------------------------------------------------------------------
def get_remaining_timeout_or_zero(time_end):
        time_now = time.time()
        return 0 if (time_now >= time_end) \
               else time_end - time_now


#===============================================================================
#===============================================================================

class Timeout_Checker(object):

    #---------------------------------------------------------------------------
    # any value less than 0 or None means infinite, the value 0 can be used to
    # indicate "do not block".
    def __init__(self, timeout_sec):

        self.timeout_sec = timeout_sec

        self.time_end = time.time()
        if (timeout_sec > 0):
            self.time_end += timeout_sec


    #---------------------------------------------------------------------------
    def is_infinite(self):
        return (self.timeout_sec < 0)

    #---------------------------------------------------------------------------
    # this returns a value greater or equal zero, negative values indicate that
    # the timeout is infinite
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

            # adapt sleep time to not exceed the remaining time
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
            timeout = Timeout_Checker(-1), # infinite timeout
            newline = None, # use universal newline mode by default
            mode = 'rt', # read-only text file
            checker_func = None ):

        while True:

            if os.path.isfile(self.name):
                f = open(self.name, mode, newline=newline)
                if f:
                    fd = f.fileno()
                    flag = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)

                return f

            if not timeout or timeout.has_expired():
                return None

            if checker_func and not checker_func():
                return None

            # wait and try again. Using 100 ms seems a good trade-off here, so
            # we don't block for too long or cause much CPU load
            timeout.sleep(0.1)


    #---------------------------------------------------------------------------
    def start_monitor(self, printer, checker_func = None):

        # time starts ticking now, since the system is running. The file may
        # not be created until any data is writte into it, so successfully
        # opening it can take a while.
        start = datetime.datetime.now()
        f_log = self.open_non_blocking(checker_func = checker_func)
        if not f_log:
            printer.print(
                '[{}] monitor terminated, could not open: {}'.format(
                    self, self.name))
            return


        #-----------------------------------------------------------------------
        def readline_loop():
            line = ""
            while True:
                # readline() returns a string terminated by "\n" for every
                # complete line. On timeout (ie. EOF reached), there is no
                # terminating "\n"
                # Unfortunately, there is a line break bug in some logs,
                # where "\n\r" (LF+CR) is used instead of "\r\n" (CR+LF).
                # Universal newline handling only considers "\r", "\n" and
                # "\r\n" as line break, thus "\n\r" is taken as two line
                # breaks and we see a lot of empty lines in the logs
                line += f_log.readline()
                if line.endswith("\n"):
                    return line

                # could not read a complete line, check termination request
                if checker_func and not checker_func():
                    return line

                # wait and try again. Using 100 ms seems a good
                # trade-off here, so we don't block for too long or
                # cause too much CPU load
                time.sleep(0.1)

        #-----------------------------------------------------------------------
        def monitoring_thread():
            with f_log:
                is_abort = False
                while not is_abort:
                    line = readline_loop()
                    is_abort = not line.endswith('\n')

                    printer.print('[{}] {}'.format(
                        datetime.datetime.now() - start,
                        line.strip()))

            # printer.print('[{}] monitor terminated for {}'.format(self, self.name))


        threading.Thread(
            target = monitoring_thread,
            args = ()
        ).start()

    #---------------------------------------------------------------------------
    @classmethod
    def do_find_match_in_lines(cls, hLog, regex, timeout = None):

        regex_compiled = re.compile( regex )
        line = ''

        while True:

            # if we've opened the file in non-blocking mode, this is a
            # non-blocking read, ie if we read something not ending with '\n',
            # it means we have reached the end of input
            line += hLog.readline()
            is_timeout = (timeout is None) or timeout.has_expired()
            if (not line.endswith('\n')) and (not is_timeout):
                # sleep 100 ms or what is left from the timeout. We can use any
                # value here, 100 ms seem a good trade-off between blocking and
                # just wasting CPU time.
                timeout.sleep(0.1)

            else:
                mo = regex_compiled.search(line)
                if mo:
                    return mo.group(0)

                if is_timeout:
                    return None

                line = ''


    #---------------------------------------------------------------------------
    @classmethod
    def do_match_sequence(cls, hLog, str_arr, timeout = None):
        for idx, expr in enumerate(str_arr):
            regex = re.escape(expr)
            match = cls.do_find_match_in_lines(hLog, regex, timeout)
            if match is None:
                return (False, idx)

            # we don't support any wildcards for now
            assert(match == expr)

        # done with the sequence, all strings found
        return (True, None)


    #---------------------------------------------------------------------------
    @classmethod
    def do_match_multiple_sequences(cls, hLog, seq_arr, timeout = None):
        for idx, (str_arr, timeout_sec) in enumerate(seq_arr):
            # we already have the first timeout running, for for every
            # further element we set up a new timeout
            if (idx > 0):
                timeout = Timeout_Checker(timeout_sec)

            (ret, idx2) = cls.do_match_sequence(hLog, str_arr, timeout)
            if not ret:
                return (False, idx, idx2)

        # done with the array of sequences
        return (True, None, None)


    #---------------------------------------------------------------------------
    def find_match_in_lines(self, regex, timeout = None):
        hLog = self.open_non_blocking(timeout = timeout)
        if not hLog:
            raise Exception('could not open: {}'.format(self.name))

        with hLog:
            return self.do_find_match_in_lines(hLog, regex, timeout)


    #---------------------------------------------------------------------------
    def match_sequence(self, str_arr, timeout = None):
        hLog = self.open_non_blocking(timeout = timeout)
        if not hLog:
            raise Exception('could not open: {}'.format(self.name))

        with hLog:
            return self.do_match_sequence(hLog, str_arr, timeout)


    #---------------------------------------------------------------------------
    def match_multiple_sequences(self, seq_arr):

        # opening the file counts towards the first sequences timeout
        (expr_array, timeout_sec) = seq_arr[0]
        timeout = Timeout_Checker(timeout_sec)

        hLog = self.open_non_blocking(timeout = timeout)
        if not hLog:
            raise Exception('could not open: {}'.format(self.name))

        with hLog:
            return self.do_match_multiple_sequences(hLog, seq_arr, timeout)