"""
Logs parser

This module allows the user to parse a log searching in it in a way that is
useful for testing. Such operations like looking for a regex match are
performed "online" on the log until the match condition happens or a timeout
occurred
"""

import time
import re
import fcntl
import os


#------------------------------------------------------------------------------
def open_file_non_blocking(file_name, mode, newline=None):
    """
    Opens a file and set non blocking OS flag

    Args:
    file_name(str): the file full path
    mode: mode to pass to open()
    nl(str, optional): newline

    Returns:
    f(file): the file object
    """

    f = open(file_name, mode, newline=newline)
    fd = f.fileno()
    flag = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flag | os.O_NONBLOCK)
    flag = fcntl.fcntl(fd, fcntl.F_GETFL)

    return f


#------------------------------------------------------------------------------
def get_remaining_timeout_or_zero(time_end):
    time_now = time.time()
    return 0 if (time_now >= time_end) else time_end - time_now;


#------------------------------------------------------------------------------
def read_line_from_log_file_with_timeout(f, timeout_sec=0):
    """
    Read a line from a logfile with a timeout. If the timeout is 0, it is
    disabled. The file handle must be opened in non-blocking mode.
    """

    time_end = time.time() + timeout_sec
    line = ""

    while True:
        # readline() will return a string, which is terminated by "\n" for
        # every line. For the last line of the file, it returns a string
        # that is not terminated by "\n" to indicate the end of the file. If
        # another task is appending data to the file, repeated calls to
        # readline() may return multiple strings without "\n", each containing
        # the new data written to the file.
        #
        #  loop iteration 1:     | line part |...
        #  loop iteration 2:               | line part |...
        #  ..
        #  loop iteration k:                                | line+\n |
        #
        # There is a line break bug in some logs, "\n\r" is used instead of
        # "\r\n". Universal newline handling accepts "\r", "\n" and "\r\n" as
        # line break. We end up with some empty lines then as "\n\r" is taken
        # as two line breaks.

        line += f.readline()
        if not line.endswith("\n"):
            # We consider timeouts only if we have to block. As long as there
            # is no blocking operation, we don't care about the timeouts. The
            # rational is, that processing the log could be slow, but all data
            # is in the logs already. We don't want to fail just because we hit
            # some timeout. If a root test executor is really concerned about
            # tests running too long, it must setup a separate watchdog that
            # simply kills the test.
            new_timeout = get_remaining_timeout_or_zero(time_end)
            if (0 == new_timeout):
                print("timeout waiting for complete line (%d byte read)"%(len(line)))
                return None

            # we still have time left, so sleep a while and check again. Note
            # that we don't check for a timeout immediately after the sleep.
            # Rationale is, that waiting for a fixed time is useless, if we
            # know this would make us run into a timeout - we should not wait
            # at all in this case.
            time.sleep( min(0.5, new_timeout) )
            continue

        # we have reached the end of a line, return it
        return line


#------------------------------------------------------------------------------
def get_match_in_line(f, regex, timeout_sec=0):
    """
    Gets the first regex match in a text file parsing it line by line.

    Args:
    f(file): the file handler of the log (shall be opened for non-blocking op)
    regex(Pattern): a compiled regular expression to look for
    timeout_sec(int, optional): timeout in seconds, 0 means disabled

    Returns:
    text(str): the text from the begin of the search until the first match or the end
    match(str): the matching string
    """

    regex_compiled = re.compile( regex )
    time_end = time.time() + timeout_sec
    text    = ""

    while True:

        # timeouts apply only, when a function would block, we don't want to
        # fail if there is data, but we've run out of time. Thus we set the
        # timeout to 0 if we have run out of time, so any blocking would lead
        # to an error.
        new_timeout = get_remaining_timeout_or_zero(time_end)
        line = read_line_from_log_file_with_timeout(f, new_timeout)
        if line is None:
            print("timeout waiting for next line (%d byte read)"%(len(text)))
            return (text, None)

        text += line
        mo = regex_compiled.search(line)
        if mo:
            return (text, mo.group(0))


#-------------------------------------------------------------------------------
def check_log_match_sequence(f, expr_array, timeout_sec=0):
    """
    Takes an array of regular expressions and perform the simple test. The
    order of the elements in the array matters, must be the same order in the
    log file

    Args:
    f(file): the file handler of the log (shall be opened for non-blocking op)
    expr_array: array with strings to match
    timeout_sec(int, optional): timeout in seconds, 0 means disabled
    """

    text = ""
    time_end = time.time() + timeout_sec

    for expr in expr_array:

        new_timeout = get_remaining_timeout_or_zero(time_end)

        (text_part, match) = get_match_in_line(f, re.escape(expr), timeout_sec)
        text += text_part
        if match is None:
            print("No match for '%s'" % expr)
            return (False, text, expr)

        # we don't support any wildcards for now
        assert(match == expr)

    return (True, text, None)


#-------------------------------------------------------------------------------
def check_log_match_set(f, expr_array, timeout_sec=0):
    """
    Take an array of regular expressions and perform the simple test. The order
    of the elements in the array does not matter, the matches just have to be
    there in the log occurring at any time at the least once per single
    expression

    Args:
    f(file): the file handler of the log (shall be opened for non-blocking op)
    expr_array: array with strings to match
    timeout_sec(int, optional): timeout in seconds, 0 means disabled
    """

    expr_dict = {}
    for expr in expr_array:
        expr_dict[expr] = re.compile( re.escape(expr) )

    text = ""
    time_end = time.time() + timeout_sec

    while True:

        # timeouts apply only, when a function would block, we don't want to
        # fail if there is data, but we've run out of time. Thus we set the
        # timeout to 0 if we have run out of time, so any blocking would lead
        # to an error.
        new_timeout = get_remaining_timeout_or_zero(time_end)
        line = read_line_from_log_file_with_timeout(f, new_timeout)
        if line is None:
            print("timeout waiting for next line (%d byte read)"%(len(text)))
            return (False, text, expr_dict.keys())

        text += line

        # we can't modify the dictionary while iterating over it, thus we
        # create a list of itmes to remove
        remove_expr = [];
        for expr in expr_dict:
            regex_compiled = expr_dict[expr]
            mo = regex_compiled.search(line)
            if not mo:
                continue

            match = mo.group(0)
            assert(match == expr) # we don't support any wildcards for now
            remove_expr.append(expr)

        # remove expression we have found
        if remove_expr:
            for expr in remove_expr:
                expr_dict.pop(expr)

            if not expr_dict:
                return (True, text, None)
