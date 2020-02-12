import time
import logs
import re

def assert_log_match(regex, log, timeout=0):
    """asserts the existence of a regex in a line of the log file and return the
    tuple (text, match) where the match is the text matching the expression and
    text is the log file content until the encountered match"""

    (text, match) = logs.get_match_in_line(log, re.compile(regex), timeout)
    assert re.escape(match) == regex

    return (text, match)

def run_test_log_match(fixture, test_system, expr, timeout=0):
    """performs the simplest test by getting the log file from the fixture and
    then assert the match of the regular expression in a line of the log"""

    test_run = fixture(test_system)
    f_out = test_run[1]

    return assert_log_match(re.escape(expr), f_out, timeout)

def run_test_log_match_sequence(fixture, test_system, expr_array, timeout=0):
    """will take an array of regular expressions and perform the simple test.
    The order of the elements in the array matters, must be the same order in
    the log file"""

    test_run = fixture(test_system)
    f_out = test_run[1]

    start   = time.time()
    elapsed = 0

    for expr in expr_array:
        remaining_time = timeout - elapsed
        assert remaining_time > 0
        assert_log_match(re.escape(expr), f_out, remaining_time)
        elapsed += time.time() - start

def run_test_log_match_set(fixture, test_system, expr_array, timeout=0):
    """will take an array of regular expressions and perform the simple test.
    The order of the elements in the array does not matter, the matches just
    have to be there in the log occuring at any time at the least once per
    single expression"""

    # TODO: this implementation in not optimal, optimize

    # make sure that the timeout is not consumed in booting the application
    fixture(test_system)

    start   = time.time()
    elapsed = 0

    for expr in expr_array:
        remaining_time = timeout - elapsed
        assert remaining_time > 0
        run_test_log_match(fixture, test_system, expr, remaining_time)
        elapsed += time.time() - start
