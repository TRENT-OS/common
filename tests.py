#
# This file is a candidate for deprecation. It contains convenience functions to
# wrap things that were non-trivial once. However, the APIs have been improved,
# so tests should implement the steps does in the wrapper function directly.
#

#-------------------------------------------------------------------------------
def run_test_log_match_sequence(fixture, test_system, expr_list, timeout_sec=0):
    """Take a list containing strings or compiles regular expressions and checks
    if each entry matched in the given order."""

    # Start the system, if it is not already running. Check if the general boot
    # went well, or raise an exception otherwise to abort the test.
    test_runner = fixture(test_system)

    log = test_runner.get_system_log_line_reader()
    ret = log.find_matches_in_lines( (expr_list, timeout_sec) )
    if not ret.ok:
        raise Exception(f'missing string #{len(ret.items)-1}: {ret.get_missing()}')

    # There is no specific return value in success


#-------------------------------------------------------------------------------
def run_test_log_match_set(fixture, test_system, expr_set, timeout_sec=0):
    """Take a set containing strings or compiles regular expressions (if a list
    is passed, it will be concerted into a set internally), and checks if the
    exists in the log. The order of the elements does not matter"""

    if isinstance(expr_set, list):
        expr_set = set(expr_set)

    # Start the system, if it is not already running. Check if the general boot
    # went well, or raise an exception otherwise to abort the test.
    test_runner = fixture(test_system)

    log = test_runner.get_system_log_line_reader()
    ret = log.find_matches_in_lines( (expr_set, timeout_sec) )
    if not ret.ok:
        raise Exception(f'missing strings: {ret.get_missing()}')

    # There is no specific return value in success
