# This is a test suite for Kconfiglib. It runs selftests on Kconfigs provided
# by us and tests compatibility with the C Kconfig implementation by comparing
# the output of Kconfiglib with the output of the scripts/kconfig/*conf
# utilities for different targets and defconfigs. It should be run from the
# top-level kernel directory with
#
#  $ python Kconfiglib/testsuite.py
#
# Some additional options can be turned on by passing arguments. With no argument,
# they default to off.
#
#  - speedy:
#    Run scripts/kconfig/conf directly when comparing outputs instead of using
#    'make' targets. Makes things a lot faster, but could break if Kconfig
#    files start depending on additional environment variables besides ARCH and
#    SRCARCH. (These would be set in the Makefiles in that case.) Safe as of
#    Linux 4.1.0-rc8.
#
#  - obsessive:
#    By default, only valid arch/defconfig pairs will be tested. With this
#    enabled, every arch will be tested with every defconfig, which increases
#    the test time by an order of magnitude. Occasionally finds (usually very
#    obscure) bugs, and I make sure everything passes with it.
#
#  - log:
#    Log timestamped failures of the defconfig test to test_defconfig_fails in
#    the root. Especially handy in obsessive mode.
#
# For example, to run in speedy mode with logging, run
#
#  $ python Kconfiglib/testsuite.py speedy log
#
# (PyPy also works, and runs the defconfig tests roughly 20% faster on my
# machine. Some of the other tests get an even greater speed-up.)
#
# The tests have been roughly arranged in order of time needed.
#
# All tests should pass. Report regressions to ulfalizer a.t Google's email
# service.

from __future__ import print_function

import kconfiglib
import os
import platform
import re
import subprocess
import sys
import textwrap
import time

speedy_mode = False
obsessive_mode = False
log_mode = False

# Assign this to avoid warnings from Kconfiglib. Nothing in the kernel's
# Kconfig files seems to actually look at the value as of 3.7.0-rc8. This is
# only relevant for the test suite, as this will get set by the kernel Makefile
# when using (i)scriptconfig.
os.environ["KERNELVERSION"] = "3.7.0"

# Prevent accidental loading of configuration files by removing
# KCONFIG_ALLCONFIG from the environment
os.environ.pop("KCONFIG_ALLCONFIG", None)

# Number of arch/defconfig pairs tested so far
nconfigs = 0

def run_tests():
    global speedy_mode, obsessive_mode, log_mode
    for s in sys.argv[1:]:
        if s == "speedy":
            speedy_mode = True
            print("Speedy mode enabled")
        elif s == "obsessive":
            obsessive_mode = True
            print("Obsessive mode enabled")
        elif s == "log":
            log_mode = True
            print("Log mode enabled")
        else:
            print("Unrecognized option '{}'".format(s))

            return

    run_selftests()
    run_compatibility_tests()

def run_selftests():
    """Runs tests on specific configurations provided by us."""

    #
    # Helper functions
    #

    def verify_value(sym_name, val):
        """Verifies that a symbol has a particular value."""
        sym = c[sym_name]
        sym_val = sym.get_value()
        verify(sym_val == val,
               "{} should have the value '{}' but has the value '{}'"
               .format(sym_name, val, sym_val))

    def assign_and_verify_new_value(sym_name, user_val, new_val):
        """Assigns a user value to the symbol and verifies the new value."""
        sym = c[sym_name]
        sym_old_val = sym.get_value()
        sym.set_user_value(user_val)
        sym_new_val = sym.get_value()
        verify(sym_new_val == new_val,
               "{} should have the new value '{}' after being assigned the "
               "user value '{}'. Instead, the value is '{}'. The old "
               "value was '{}'."
               .format(sym_name, new_val, user_val, sym_new_val, sym_old_val))

    def assign_and_verify_new_user_value(sym_name, user_val, new_user_val):
        """Assigns a user value to the symbol and verifies the new user
        value."""
        sym = c[sym_name]
        sym_old_user_val = sym.get_user_value()
        sym.set_user_value(user_val)
        sym_new_user_val = sym.get_user_value()
        verify(sym_new_user_val == new_user_val,
               "{} should have the user value '{}' after being assigned "
               "the user value '{}'. Instead, the new user value was '{}'. "
               "The old user value was '{}'."
               .format(sym_name, new_user_val, user_val, sym_new_user_val,
                       sym_old_user_val))

    print("Running selftests...\n")

    print("Testing tristate comparisons...")

    def verify_truth_table(comp_fn, *bools):
        bools_list = list(bools)
        for (x, y) in (("n", "n"), ("n", "m"), ("n", "y"),
                       ("m", "n"), ("m", "m"), ("m", "y"),
                       ("y", "n"), ("y", "m"), ("y", "y")):
            expected = bools_list.pop(0)
            verify(comp_fn(x, y) == expected,
                   "Expected {} on ('{}', '{}') to be {}".
                   format(comp_fn, x, y, expected))

    verify_truth_table(kconfiglib.tri_less,
                       False, True, True,
                       False, False, True,
                       False, False, False)

    verify_truth_table(kconfiglib.tri_less_eq,
                       True, True, True,
                       False, True, True,
                       False, False, True)

    verify_truth_table(kconfiglib.tri_greater,
                       False, False, False,
                       True, False, False,
                       True, True, False)

    verify_truth_table(kconfiglib.tri_greater_eq,
                       True, False, False,
                       True, True, False,
                       True, True, True)

    #
    # String literal lexing. (This tests an internal API.)
    #

    print("Testing string literal (constant symbol) lexing...")

    c = kconfiglib.Config("Kconfiglib/tests/empty")

    def verify_string_lex(s, res):
        """Verifies that the string token 'res' is produced from lexing 's'.
        Strips the first and last characters from 's' so we can use readable
        raw strings as input."""
        s = s[1:-1]
        s_res = c._tokenize(s, for_eval = True).get_next()
        verify(s_res == res,
               "'{}' produced the string token '{}'. Expected '{}'."
               .format(s, s_res, res))

    verify_string_lex(r""" "" """, "")
    verify_string_lex(r""" '' """, "")

    verify_string_lex(r""" "a" """, "a")
    verify_string_lex(r""" 'a' """, "a")
    verify_string_lex(r""" "ab" """, "ab")
    verify_string_lex(r""" 'ab' """, "ab")
    verify_string_lex(r""" "abc" """, "abc")
    verify_string_lex(r""" 'abc' """, "abc")

    verify_string_lex(r""" "'" """, "'")
    verify_string_lex(r""" '"' """, '"')

    verify_string_lex(r""" "\"" """, '"')
    verify_string_lex(r""" '\'' """, "'")

    verify_string_lex(r""" "\"\"" """, '""')
    verify_string_lex(r""" '\'\'' """, "''")

    verify_string_lex(r""" "\'" """, "'")
    verify_string_lex(r""" '\"' """, '"')

    verify_string_lex(r""" "\\" """, "\\")
    verify_string_lex(r""" '\\' """, "\\")

    verify_string_lex(r""" "\a\\'\b\c\"'d" """, 'a\\\'bc"\'d')
    verify_string_lex(r""" '\a\\"\b\c\'"d' """, "a\\\"bc'\"d")

    def verify_string_bad(s):
        """Verifies that tokenizing 's' throws a Kconfig_Syntax_Error. Strips
        the first and last characters from 's' so we can use readable raw
        strings as input."""
        s = s[1:-1]
        try:
            c._tokenize(s, for_eval = True)
        except kconfiglib.Kconfig_Syntax_Error:
            pass
        else:
            fail("Tokenization of '{}' should have failed.".format(s))

    verify_string_bad(r""" " """)
    verify_string_bad(r""" ' """)
    verify_string_bad(r""" "' """)
    verify_string_bad(r""" '" """)
    verify_string_bad(r""" "\" """)
    verify_string_bad(r""" '\' """)
    verify_string_bad(r""" "foo """)
    verify_string_bad(r""" 'foo """)

    #
    # is_modifiable()
    #

    print("Testing is_modifiable() and range queries...")

    c = kconfiglib.Config("Kconfiglib/tests/Kmodifiable")

    for sym_name in ("VISIBLE", "TRISTATE_SELECTED_TO_M", "VISIBLE_STRING",
                     "VISIBLE_INT", "VISIBLE_HEX"):
        sym = c[sym_name]
        verify(sym.is_modifiable(),
               "{} should be modifiable".format(sym_name))

    for sym_name in ("n", "m", "y", "NOT_VISIBLE", "SELECTED_TO_Y",
                     "BOOL_SELECTED_TO_M", "M_VISIBLE_TRISTATE_SELECTED_TO_M",
                     "NOT_VISIBLE_STRING", "NOT_VISIBLE_INT", "NOT_VISIBLE_HEX"):
        sym = c[sym_name]
        verify(not sym.is_modifiable(),
               "{} should not be modifiable".format(sym_name))

    #
    # get_lower/upper_bound() and get_assignable_values()
    #

    c = kconfiglib.Config("Kconfiglib/tests/Kbounds")

    def verify_bounds(sym_name, low, high):
        sym = c[sym_name]
        sym_low = sym.get_lower_bound()
        sym_high = sym.get_upper_bound()
        verify(sym_low == low and sym_high == high,
               "Incorrectly calculated bounds for {}: {}-{}. "
               "Expected {}-{}.".format(sym_name, sym_low, sym_high,
                                          low, high))
        # See that we get back the corresponding range from
        # get_assignable_values()
        if sym_low is None:
            vals = sym.get_assignable_values()
            verify(vals == [],
                   "get_assignable_values() thinks there should be assignable "
                   "values for {} ({}) but not get_lower/upper_bound()".
                   format(sym_name, vals))
            if sym.get_type() in (kconfiglib.BOOL, kconfiglib.TRISTATE):
                verify(not sym.is_modifiable(),
                       "get_lower_bound() thinks there should be no "
                       "assignable values for the bool/tristate {} but "
                       "is_modifiable() thinks it should be modifiable".
                       format(sym_name))
        else:
            tri_to_int = { "n" : 0, "m" : 1, "y" : 2 }
            bound_range = ["n", "m", "y"][tri_to_int[sym_low] :
                                          tri_to_int[sym_high] + 1]
            assignable_range = sym.get_assignable_values()
            verify(bound_range == assignable_range,
                   "get_lower/upper_bound() thinks the range for {} should "
                   "be {} while get_assignable_values() thinks it should be "
                   "{}".format(sym_name, bound_range, assignable_range))
            if sym.get_type() in (kconfiglib.BOOL, kconfiglib.TRISTATE):
                verify(sym.is_modifiable(),
                       "get_lower/upper_bound() thinks the range for the "
                       "bool/tristate {} should be {} while is_modifiable() "
                       "thinks the symbol should not be modifiable".
                       format(sym_name, bound_range))

    verify_bounds("n", None, None)
    verify_bounds("m", None, None)
    verify_bounds("y", None, None)
    verify_bounds("Y_VISIBLE_BOOL", "n", "y")
    verify_bounds("Y_VISIBLE_TRISTATE", "n", "y")
    verify_bounds("M_VISIBLE_BOOL", "n", "y")
    verify_bounds("M_VISIBLE_TRISTATE", "n", "m")
    verify_bounds("Y_SELECTED_BOOL", None, None)
    verify_bounds("M_SELECTED_BOOL", None, None)
    verify_bounds("Y_SELECTED_TRISTATE", None, None)
    verify_bounds("M_SELECTED_TRISTATE", "m", "y")
    verify_bounds("M_SELECTED_M_VISIBLE_TRISTATE", None, None)
    verify_bounds("N_IMPLIED_BOOL", "n", "y")
    verify_bounds("N_IMPLIED_TRISTATE", "n", "y")
    verify_bounds("M_IMPLIED_BOOL", "n", "y")
    verify_bounds("M_IMPLIED_TRISTATE", "n", "y")
    verify_bounds("Y_IMPLIED_BOOL", "n", "y")
    verify_bounds("Y_IMPLIED_TRISTATE", "n", "y")
    verify_bounds("STRING", None, None)
    verify_bounds("INT", None, None)
    verify_bounds("HEX", None, None)

    #
    # eval()
    #

    print("Testing eval()...")

    c = kconfiglib.Config("Kconfiglib/tests/Keval")

    def verify_eval(expr, val):
        res = c.eval(expr)
        verify(res == val,
               "'{}' evaluated to {}, expected {}".format(expr, res, val))

    def verify_eval_bad(expr):
        try:
            c.eval(expr)
        except kconfiglib.Kconfig_Syntax_Error:
            pass
        else:
            fail('eval("{}") should throw Kconfig_Syntax_Error'
                 .format(expr))

    # No modules
    verify_eval("n", "n")
    verify_eval("m", "n")
    verify_eval("y", "y")
    verify_eval("'n'", "n")
    verify_eval("'m'", "n")
    verify_eval("'y'", "y")
    verify_eval("M", "y")
    # Modules
    c["MODULES"].set_user_value("y")
    verify_eval("n", "n")
    verify_eval("m", "m")
    verify_eval("y", "y")
    verify_eval("'n'", "n")
    verify_eval("'m'", "m")
    verify_eval("'y'", "y")
    verify_eval("M", "m")
    verify_eval("(Y || N) && (m && y)", "m")

    # Non-bool/non-tristate symbols are always "n" in a tristate sense
    verify_eval("Y_STRING", "n")
    verify_eval("Y_STRING || m", "m")

    # As are all constants besides "y" and "m"
    verify_eval('"foo"', "n")
    verify_eval('"foo" || "bar"', "n")

    # Test equality for symbols

    verify_eval("N = N", "y")
    verify_eval("N = n", "y")
    verify_eval("N = 'n'", "y")
    verify_eval("N != N", "n")
    verify_eval("N != n", "n")
    verify_eval("N != 'n'", "n")

    verify_eval("M = M", "y")
    verify_eval("M = m", "y")
    verify_eval("M = 'm'", "y")
    verify_eval("M != M", "n")
    verify_eval("M != m", "n")
    verify_eval("M != 'm'", "n")

    verify_eval("Y = Y", "y")
    verify_eval("Y = y", "y")
    verify_eval("Y = 'y'", "y")
    verify_eval("Y != Y", "n")
    verify_eval("Y != y", "n")
    verify_eval("Y != 'y'", "n")

    verify_eval("N != M", "y")
    verify_eval("N != Y", "y")
    verify_eval("M != Y", "y")

    # string/int/hex
    verify_eval("Y_STRING = y", "y")
    verify_eval("Y_STRING = 'y'", "y")
    verify_eval('FOO_BAR_STRING = "foo bar"', "y")
    verify_eval('FOO_BAR_STRING != "foo bar baz"', "y")
    verify_eval('INT_37 = 37', "y")
    verify_eval("INT_37 = '37'", "y")
    verify_eval('HEX_0X37 = 0x37', "y")
    verify_eval("HEX_0X37 = '0x37'", "y")

    # These should also hold after 31847b67 (kconfig: allow use of relations
    # other than (in)equality)
    verify_eval("HEX_0X37 = '0x037'", "y")
    verify_eval("HEX_0X37 = '0x0037'", "y")

    # Compare some constants...
    verify_eval('"foo" != "bar"', "y")
    verify_eval('"foo" = "bar"', "n")
    verify_eval('"foo" = "foo"', "y")
    # Undefined symbols get their name as their value
    c.set_print_warnings(False)
    verify_eval("'not_defined' = not_defined", "y")
    verify_eval("not_defined_2 = not_defined_2", "y")
    verify_eval("not_defined_1 != not_defined_2", "y")

    # Test less than/greater than

    # Basic evaluation
    verify_eval("INT_37 < 38", "y")
    verify_eval("38 < INT_37", "n")
    verify_eval("INT_37 < '38'", "y")
    verify_eval("'38' < INT_37", "n")
    verify_eval("INT_37 < 138", "y")
    verify_eval("138 < INT_37", "n")
    verify_eval("INT_37 < '138'", "y")
    verify_eval("'138' < INT_37", "n")
    verify_eval("INT_37 < -138", "n")
    verify_eval("-138 < INT_37", "y")
    verify_eval("INT_37 < '-138'", "n")
    verify_eval("'-138' < INT_37", "y")
    verify_eval("INT_37 < 37", "n")
    verify_eval("37 < INT_37", "n")
    verify_eval("INT_37 < 36", "n")
    verify_eval("36 < INT_37", "y")

    # Different formats in comparison
    verify_eval("INT_37 < 0x26", "y") # 38
    verify_eval("INT_37 < 0x25", "n") # 37
    verify_eval("INT_37 < 0x24", "n") # 36
    verify_eval("HEX_0X37 < 56", "y") # 0x38
    verify_eval("HEX_0X37 < 55", "n") # 0x37
    verify_eval("HEX_0X37 < 54", "n") # 0x36

    # Other int comparisons
    verify_eval("INT_37 <= 38", "y")
    verify_eval("INT_37 <= 37", "y")
    verify_eval("INT_37 <= 36", "n")
    verify_eval("INT_37 >  38", "n")
    verify_eval("INT_37 >  37", "n")
    verify_eval("INT_37 >  36", "y")
    verify_eval("INT_37 >= 38", "n")
    verify_eval("INT_37 >= 37", "y")
    verify_eval("INT_37 >= 36", "y")

    # Other hex comparisons
    verify_eval("HEX_0X37 <= 0x38", "y")
    verify_eval("HEX_0X37 <= 0x37", "y")
    verify_eval("HEX_0X37 <= 0x36", "n")
    verify_eval("HEX_0X37 >  0x38", "n")
    verify_eval("HEX_0X37 >  0x37", "n")
    verify_eval("HEX_0X37 >  0x36", "y")
    verify_eval("HEX_0X37 >= 0x38", "n")
    verify_eval("HEX_0X37 >= 0x37", "y")
    verify_eval("HEX_0X37 >= 0x36", "y")

    # A hex holding a value without a "0x" prefix should still be treated as
    # hexadecimal
    verify_eval("HEX_37 < 0x38", "y")
    verify_eval("HEX_37 < 0x37", "n")
    verify_eval("HEX_37 < 0x36", "n")

    # Symbol comparisons
    verify_eval("INT_37   <  HEX_0X37", "y")
    verify_eval("INT_37   >  HEX_0X37", "n")
    verify_eval("HEX_0X37 <  INT_37  ", "n")
    verify_eval("HEX_0X37 >  INT_37  ", "y")
    verify_eval("INT_37   <  INT_37  ", "n")
    verify_eval("INT_37   <= INT_37  ", "y")
    verify_eval("INT_37   >  INT_37  ", "n")
    verify_eval("INT_37   <= INT_37  ", "y")

    # Strings compare lexicographically
    verify_eval("'aa' < 'ab'", "y")
    verify_eval("'aa' > 'ab'", "n")
    verify_eval("'ab' < 'aa'", "n")
    verify_eval("'ab' > 'aa'", "y")

    # If one operand is numeric and the other not a valid number, we get 'n'
    verify_eval("INT_37 <  oops  ", "n")
    verify_eval("INT_37 <= oops  ", "n")
    verify_eval("INT_37 >  oops  ", "n")
    verify_eval("INT_37 >= oops  ", "n")
    verify_eval("oops   <  INT_37", "n")
    verify_eval("oops   <= INT_37", "n")
    verify_eval("oops   >  INT_37", "n")
    verify_eval("oops   >= INT_37", "n")

    # The C implementation's parser can be pretty lax about syntax. Kconfiglib
    # sometimes needs to emulate that. Verify that some bad stuff throws
    # Kconfig_Syntax_Error at least.
    verify_eval_bad("")
    verify_eval_bad("&")
    verify_eval_bad("|")
    verify_eval_bad("!")
    verify_eval_bad("(")
    verify_eval_bad(")")
    verify_eval_bad("=")
    verify_eval_bad("(X")
    verify_eval_bad("X &&")
    verify_eval_bad("&& X")
    verify_eval_bad("X ||")
    verify_eval_bad("|| X")

    #
    # Text queries
    #

    print("Testing text queries...")

    def verify_print(o, s):
        verify_equals(str(o), textwrap.dedent(s[1:]))

    for var in ("ARCH", "SRCARCH", "srctree"):
        os.environ.pop(var, None)

    # The tests below aren't meant to imply that the format is set in stone.
    # It's just to verify that the strings do not change unexpectedly.

    # Printing of Config

    c = kconfiglib.Config("Kconfiglib/tests/Ktext")

    verify_print(c, """
      Configuration
      File                                   : Kconfiglib/tests/Ktext
      Base directory                         : .
      Value of $ARCH at creation time        : (not set)
      Value of $SRCARCH at creation time     : (not set)
      Source tree (derived from $srctree;
      defaults to '.' if $srctree isn't set) : .
      Most recently loaded .config           : (no .config loaded)
      Print warnings                         : true
      Print assignments to undefined symbols : false""")

    os.environ["ARCH"] = "foo"
    os.environ["SRCARCH"] = "bar"
    os.environ["srctree"] = "baz"

    c = kconfiglib.Config("Kconfiglib/tests/Ktext", base_dir = "foobar")
    c.load_config("Kconfiglib/tests/empty")
    c.set_print_warnings(False)
    c.set_print_undef_assign(True)

    verify_print(c, """
      Configuration
      File                                   : Kconfiglib/tests/Ktext
      Base directory                         : foobar
      Value of $ARCH at creation time        : foo
      Value of $SRCARCH at creation time     : bar
      Source tree (derived from $srctree;
      defaults to '.' if $srctree isn't set) : baz
      Most recently loaded .config           : Kconfiglib/tests/empty
      Print warnings                         : false
      Print assignments to undefined symbols : true""")

    # Printing of Symbol

    verify_print(c["BASIC"], """
      Symbol BASIC
      Type           : bool
      Value          : "n"
      User value     : (no user value)
      Visibility     : "n"
      Is choice item : false
      Is defined     : true
      Is from env.   : false
      Is special     : false
      Prompts:
       (no prompts)
      Default values:
       (no default values)
      Selects:
       (no selects)
      Implies:
       (no implies)
      Reverse (select-related) dependencies:
       (no reverse dependencies)
      Weak reverse (imply-related) dependencies:
       (no weak reverse dependencies)
      Additional dependencies from enclosing menus and ifs:
       (no additional dependencies)
      Locations: Kconfiglib/tests/Ktext:1""")

    c["ADVANCED"].set_user_value("m")

    verify_print(c["ADVANCED"], """
      Symbol ADVANCED
      Type           : tristate
      Value          : "y"
      User value     : "m"
      Visibility     : "y"
      Is choice item : false
      Is defined     : true
      Is from env.   : false
      Is special     : false
      Prompts:
       "advanced prompt 1" if y || BASIC && BASIC (value: "y")
       "advanced prompt 2"
      Default values:
       y (value: "y")
        Condition: BASIC && !BASIC (value: "n")
       n (value: "n")
        Condition: BASIC = DUMMY && X < Y && X <= Y && X > Y && X >= Y (value: "n")
      Selects:
       SELECTED_1 if BASIC && DUMMY (value: "n")
       SELECTED_2 if !(DUMMY || BASIC) (value: "y")
      Implies:
       IMPLIED_1 if BASIC || DUMMY (value: "n")
       IMPLIED_2 if !(DUMMY && BASIC) (value: "y")
      Reverse (select-related) dependencies:
       SELECTING_1 && BASIC || SELECTING_2 && !BASIC (value: "n")
      Weak reverse (imply-related) dependencies:
       IMPLYING_1 && DUMMY || IMPLYING_2 && !DUMMY (value: "n")
      Additional dependencies from enclosing menus and ifs:
       !BASIC && !BASIC (value: "y")
      Locations: Kconfiglib/tests/Ktext:6 Kconfiglib/tests/Ktext:15""")

    verify_print(c["HAS_RANGES"], """
      Symbol HAS_RANGES
      Type           : int
      Value          : "1"
      User value     : (no user value)
      Visibility     : "y"
      Is choice item : false
      Is defined     : true
      Is from env.   : false
      Is special     : false
      Ranges:
       [1, 2] if !DUMMY (value: "y")
       [INT, INT] if DUMMY (value: "n")
       [123, 456]
      Prompts:
       "ranged"
      Default values:
       (no default values)
      Selects:
       (no selects)
      Implies:
       (no implies)
      Reverse (select-related) dependencies:
       (no reverse dependencies)
      Weak reverse (imply-related) dependencies:
       (no weak reverse dependencies)
      Additional dependencies from enclosing menus and ifs:
       (no additional dependencies)
      Locations: Kconfiglib/tests/Ktext:35""")

    # Printing of Choice

    verify_print(c.get_choices()[0], """
      Choice
      Name (for named choices): (no name)
      Type            : bool
      Selected symbol : CHOICE_ITEM_1
      User value      : (no user value)
      Mode            : "y"
      Visibility      : "y"
      Optional        : false
      Prompts:
       "choice"
      Defaults:
       (no default values)
      Choice symbols:
       CHOICE_ITEM_1 CHOICE_ITEM_2 CHOICE_ITEM_3
      Additional dependencies from enclosing menus and ifs:
       (no additional dependencies)
      Locations: Kconfiglib/tests/Ktext:41""")

    c["CHOICE_ITEM_2"].set_user_value("y")

    verify_print(c.get_choices()[0], """
      Choice
      Name (for named choices): (no name)
      Type            : bool
      Selected symbol : CHOICE_ITEM_2
      User value      : CHOICE_ITEM_2
      Mode            : "y"
      Visibility      : "y"
      Optional        : false
      Prompts:
       "choice"
      Defaults:
       (no default values)
      Choice symbols:
       CHOICE_ITEM_1 CHOICE_ITEM_2 CHOICE_ITEM_3
      Additional dependencies from enclosing menus and ifs:
       (no additional dependencies)
      Locations: Kconfiglib/tests/Ktext:41""")

    # Printing of Menu

    verify_print(c.get_menus()[0], """
      Menu
      Title                     : simple menu
      'depends on' dependencies : (no dependencies)
      'visible if' dependencies : (no dependencies)
      Additional dependencies from enclosing menus and ifs:
       (no additional dependencies)
      Location: Kconfiglib/tests/Ktext:53""")

    verify_print(c.get_menus()[1], """
      Menu
      Title                     : advanced menu
      'depends on' dependencies : !BASIC (value: "y")
      'visible if' dependencies : !DUMMY (value: "y")
      Additional dependencies from enclosing menus and ifs:
       !DUMMY (value: "y")
      Location: Kconfiglib/tests/Ktext:57""")

    # Printing of Comment

    verify_print(c.get_comments()[0], """
      Comment
      Text: simple comment
      Dependencies: (no dependencies)
      Additional dependencies from enclosing menus and ifs:
       (no additional dependencies)
      Location: Kconfiglib/tests/Ktext:63""")

    verify_print(c.get_comments()[1], """
      Comment
      Text: advanced comment
      Dependencies: !BASIC (value: "y")
      Additional dependencies from enclosing menus and ifs:
       !DUMMY (value: "y")
      Location: Kconfiglib/tests/Ktext:66""")

    verify_equals(c["NO_HELP"].get_help(), None)
    verify_equals(c["EMPTY_HELP"].get_help(), "")
    verify_equals(c["HELP_TERMINATED_BY_COMMENT"].get_help(), "a\nb\nc\n")
    verify_equals(c["TRICKY_HELP"].get_help(),
                  "a\n b\n  c\n\n d\n  e\n   f\n\n\ng\n h\n  i\n")
    verify_equals(c["S"].get_help(), "help for\nS\n")
    verify_equals(c.get_choices()[1].get_help(), "help for\nC\n")

    verify_equals(c["S"].get_name(), "S")
    verify_equals(c.get_comments()[2].get_text(), "a comment")
    verify_equals(c.get_menus()[2].get_title(), "a menu")

    #
    # Prompt queries
    #

    print("Testing prompt queries...")

    def verify_prompts(sym_or_choice, prompts):
        sym_or_choice_prompts = sym_or_choice.get_prompts()
        verify(len(sym_or_choice_prompts) == len(prompts),
               "Wrong number of prompts for " + sym_or_choice.get_name())
        for i in range(0, len(sym_or_choice_prompts)):
            verify(sym_or_choice_prompts[i] == prompts[i],
                   "Prompt {} wrong for {}: Was '{}', should be '{}'".
                   format(i, sym_or_choice.get_name(), sym_or_choice_prompts[i],
                          prompts[i]))

    def verify_sym_prompts(sym_name, *prompts):
        verify_prompts(c[sym_name], prompts)

    def verify_choice_prompts(choice, *prompts):
        verify_prompts(choice, prompts)

    c = kconfiglib.Config("Kconfiglib/tests/Kprompt")

    # Symbols
    verify_sym_prompts("NO_PROMPT")
    verify_sym_prompts("SINGLE_PROMPT_1", "single prompt 1")
    verify_sym_prompts("SINGLE_PROMPT_2", "single prompt 2")
    verify_sym_prompts("MULTI_PROMPT", "prompt 1", "prompt 2", "prompt 3", "prompt 4")

    no_prompt_choice, single_prompt_1_choice, single_prompt_2_choice, multi_prompt_choice = \
      c.get_choices()

    # Choices
    verify_choice_prompts(no_prompt_choice)
    verify_choice_prompts(single_prompt_1_choice, "single prompt 1 choice")
    verify_choice_prompts(single_prompt_2_choice, "single prompt 2 choice")
    verify_choice_prompts(multi_prompt_choice,
      "prompt 1 choice", "prompt 2 choice", "prompt 3 choice")

    #
    # Location queries
    #

    print("Testing location queries...")

    def verify_def_locations(sym_name, *locs):
        sym_locs = c[sym_name].get_def_locations()
        verify(len(sym_locs) == len(locs),
               "Wrong number of def. locations for " + sym_name)
        for i in range(0, len(sym_locs)):
            verify(sym_locs[i] == locs[i],
                   "Wrong def. location for {}: Was {}, should be {}".
                   format(sym_name, sym_locs[i], locs[i]))

    # Expanded in the 'source' statement in Klocation
    os.environ["FOO"] = "tests"

    c = kconfiglib.Config("Kconfiglib/tests/Klocation", base_dir = "Kconfiglib/")

    verify_def_locations("n")
    verify_def_locations("m")
    verify_def_locations("y")

    verify_def_locations("A",
      ("Kconfiglib/tests/Klocation", 4),
      ("Kconfiglib/tests/Klocation", 28),
      ("Kconfiglib/tests/Klocation_included", 1),
      ("Kconfiglib/tests/Klocation_included", 3))
    verify_def_locations("C",
      ("Kconfiglib/tests/Klocation", 18))
    verify_def_locations("M",
      ("Kconfiglib/tests/Klocation_included", 6))
    verify_def_locations("N",
      ("Kconfiglib/tests/Klocation_included", 19))
    verify_def_locations("O",
      ("Kconfiglib/tests/Klocation_included", 21))
    verify_def_locations("NOT_DEFINED") # No locations

    def verify_ref_locations(sym_name, *locs):
        sym_locs = c[sym_name].get_ref_locations()
        verify(len(sym_locs) == len(locs),
               "Wrong number of ref. locations for " + sym_name)
        for i in range(0, len(sym_locs)):
            verify(sym_locs[i] == locs[i],
                   "Wrong ref. location for {}: Was {}, should be {}".
                   format(sym_name, sym_locs[i], locs[i]))

    # Reload without the slash at the end of 'base_dir' to get coverage for
    # that as well
    c = kconfiglib.Config("Kconfiglib/tests/Klocation", base_dir = "Kconfiglib")

    verify_ref_locations("A",
      ("Kconfiglib/tests/Klocation", 10),
      ("Kconfiglib/tests/Klocation", 12),
      ("Kconfiglib/tests/Klocation", 16),
      ("Kconfiglib/tests/Klocation", 34),
      ("Kconfiglib/tests/Klocation", 35),
      ("Kconfiglib/tests/Klocation_included", 7),
      ("Kconfiglib/tests/Klocation_included", 8),
      ("Kconfiglib/tests/Klocation_included", 9),
      ("Kconfiglib/tests/Klocation_included", 12),
      ("Kconfiglib/tests/Klocation_included", 13),
      ("Kconfiglib/tests/Klocation_included", 14),
      ("Kconfiglib/tests/Klocation_included", 15),
      ("Kconfiglib/tests/Klocation_included", 35),
      ("Kconfiglib/tests/Klocation_included", 40),
      ("Kconfiglib/tests/Klocation", 65),
      ("Kconfiglib/tests/Klocation", 66),
      ("Kconfiglib/tests/Klocation", 67),
      ("Kconfiglib/tests/Klocation", 68),
      ("Kconfiglib/tests/Klocation", 69),
      ("Kconfiglib/tests/Klocation", 70),
      ("Kconfiglib/tests/Klocation", 71),
      ("Kconfiglib/tests/Klocation", 72),
      ("Kconfiglib/tests/Klocation", 73))
    verify_ref_locations("C")
    verify_ref_locations("NOT_DEFINED",
      ("Kconfiglib/tests/Klocation", 12),
      ("Kconfiglib/tests/Klocation", 29),
      ("Kconfiglib/tests/Klocation_included", 12),
      ("Kconfiglib/tests/Klocation_included", 35),
      ("Kconfiglib/tests/Klocation_included", 41))

    # Location queries for choices

    def verify_choice_locations(choice, *locs):
        choice_locs = choice.get_def_locations()
        verify(len(choice_locs) == len(locs),
               "Wrong number of def. locations for choice")
        for i in range(0, len(choice_locs)):
            verify(choice_locs[i] == locs[i],
                   "Wrong def. location for choice: Was {}, should be {}".
                   format(choice_locs[i], locs[i]))

    choice_1, choice_2 = c.get_choices()

    # Throw in named choice test
    verify(choice_1.get_name() == "B",
           "The first choice should be called B")
    verify(choice_2.get_name() is None,
           "The second choice should have no name")

    verify_choice_locations(choice_1,
      ("Kconfiglib/tests/Klocation", 15),
      ("Kconfiglib/tests/Klocation_included", 24))
    verify_choice_locations(choice_2,
      ("Kconfiglib/tests/Klocation_included", 17))

    # Location queries for menus and comments

    def verify_location(menu_or_comment, loc):
        menu_or_comment_loc = menu_or_comment.get_location()
        verify(menu_or_comment_loc == loc,
               "Wrong location for {} with text '{}': Was {}, should be "
               "{}".format("menu" if menu_or_comment.is_menu() else "comment",
                            menu_or_comment.get_title() if
                              menu_or_comment.is_menu() else
                              menu_or_comment.get_text(),
                            menu_or_comment_loc,
                            loc))

    menu_1, menu_2 = c.get_menus()[:-1]
    comment_1, comment_2 = c.get_comments()

    verify_location(menu_1, ("Kconfiglib/tests/Klocation", 9))
    verify_location(menu_2, ("Kconfiglib/tests/Klocation_included", 5))
    verify_location(comment_1, ("Kconfiglib/tests/Klocation", 31))
    verify_location(comment_2, ("Kconfiglib/tests/Klocation_included", 36))

    #
    # Visibility queries
    #

    print("Testing visibility queries...")

    c = kconfiglib.Config("Kconfiglib/tests/Kvisibility")

    def verify_sym_visibility(sym_name, no_module_vis, module_vis):
        sym = c[sym_name]

        c["MODULES"].set_user_value("n")
        sym_vis = sym.get_visibility()
        verify(sym_vis == no_module_vis,
               "{} should have visibility '{}' without modules, had "
               "visibility '{}'".
               format(sym_name, no_module_vis, sym_vis))

        c["MODULES"].set_user_value("y")
        sym_vis = sym.get_visibility()
        verify(sym_vis == module_vis,
               "{} should have visibility '{}' with modules, had "
               "visibility '{}'".
               format(sym_name, module_vis, sym_vis))

    # Symbol visibility

    verify_sym_visibility("NO_PROMPT", "n", "n")
    verify_sym_visibility("BOOL_n", "n", "n")
    verify_sym_visibility("BOOL_m", "n", "y") # Promoted
    verify_sym_visibility("BOOL_MOD", "y", "y") # Promoted
    verify_sym_visibility("BOOL_y", "y", "y")
    verify_sym_visibility("TRISTATE_m", "n", "m")
    verify_sym_visibility("TRISTATE_MOD", "y", "m") # Promoted
    verify_sym_visibility("TRISTATE_y", "y", "y")
    verify_sym_visibility("BOOL_if_n", "n", "n")
    verify_sym_visibility("BOOL_if_m", "n", "y") # Promoted
    verify_sym_visibility("BOOL_if_y", "y", "y")
    verify_sym_visibility("BOOL_menu_n", "n", "n")
    verify_sym_visibility("BOOL_menu_m", "n", "y") # Promoted
    verify_sym_visibility("BOOL_menu_y", "y", "y")
    verify_sym_visibility("BOOL_choice_n", "n", "n")
    verify_sym_visibility("BOOL_choice_m", "n", "y") # Promoted
    verify_sym_visibility("BOOL_choice_y", "y", "y")
    verify_sym_visibility("TRISTATE_if_n", "n", "n")
    verify_sym_visibility("TRISTATE_if_m", "n", "m")
    verify_sym_visibility("TRISTATE_if_y", "y", "y")
    verify_sym_visibility("TRISTATE_menu_n", "n", "n")
    verify_sym_visibility("TRISTATE_menu_m", "n", "m")
    verify_sym_visibility("TRISTATE_menu_y", "y", "y")
    verify_sym_visibility("TRISTATE_choice_n", "n", "n")
    verify_sym_visibility("TRISTATE_choice_m", "n", "m")
    verify_sym_visibility("TRISTATE_choice_y", "y", "y")

    # Choice visibility

    def verify_choice_visibility(choice, no_module_vis, module_vis):
        c["MODULES"].set_user_value("n")
        choice_vis = choice.get_visibility()
        verify(choice_vis == no_module_vis,
               "choice {} should have visibility '{}' without modules, "
               "has visibility '{}'".
               format(choice.get_name(), no_module_vis, choice_vis))

        c["MODULES"].set_user_value("y")
        choice_vis = choice.get_visibility()
        verify(choice_vis == module_vis,
               "choice {} should have visibility '{}' with modules, "
               "has visibility '{}'".
               format(choice.get_name(), module_vis, choice_vis))

    choice_bool_n, choice_bool_m, choice_bool_y, choice_tristate_n, \
      choice_tristate_m, choice_tristate_y, choice_tristate_if_m_and_y, \
      choice_tristate_menu_n_and_y \
      = c.get_choices()[3:]

    verify(choice_bool_n.get_name() == "BOOL_CHOICE_n", "Ops - testing the wrong choices")

    verify_choice_visibility(choice_bool_n, "n", "n")
    verify_choice_visibility(choice_bool_m, "n", "y") # Promoted
    verify_choice_visibility(choice_bool_y, "y", "y")
    verify_choice_visibility(choice_tristate_n, "n", "n")
    verify_choice_visibility(choice_tristate_m, "n", "m")
    verify_choice_visibility(choice_tristate_y, "y", "y")

    verify_choice_visibility(choice_tristate_if_m_and_y, "n", "m")
    verify_choice_visibility(choice_tristate_menu_n_and_y, "n", "n")

    # Menu visibility

    def verify_menu_visibility(menu, no_module_vis, module_vis):
        c["MODULES"].set_user_value("n")
        menu_vis = menu.get_visibility()
        verify(menu_vis == no_module_vis,
               "menu \"{}\" should have visibility '{}' without modules, "
               "has visibility '{}'".
               format(menu.get_title(), no_module_vis, menu_vis))

        c["MODULES"].set_user_value("y")
        menu_vis = menu.get_visibility()
        verify(menu_vis == module_vis,
               "menu \"{}\" should have visibility '{}' with modules, "
               "has visibility '{}'".
               format(menu.get_title(), module_vis, menu_vis))

    menu_n, menu_m, menu_y, menu_if_n, menu_if_m, menu_if_y, \
      menu_if_m_and_y = c.get_menus()[4:-5]
    verify(menu_n.get_title() == "menu n", "Ops - testing the wrong menus")

    verify_menu_visibility(menu_n, "n", "n")
    verify_menu_visibility(menu_m, "n", "m")
    verify_menu_visibility(menu_y, "y", "y")
    verify_menu_visibility(menu_if_n, "n", "n")
    verify_menu_visibility(menu_if_m, "n", "m")
    verify_menu_visibility(menu_if_y, "y", "y")
    verify_menu_visibility(menu_if_m_and_y, "n", "m")

    # Menu 'visible if' visibility

    menu_visible_if_n, menu_visible_if_m, menu_visible_if_y, \
      menu_visible_if_m_2 = c.get_menus()[12:]

    def verify_visible_if_visibility(menu, no_module_vis, module_vis):
        c["MODULES"].set_user_value("n")
        menu_vis = menu.get_visible_if_visibility()
        verify(menu_vis == no_module_vis,
               "menu \"{}\" should have 'visible if' visibility '{}' "
               "without modules, has 'visible if' visibility '{}'".
               format(menu.get_title(), no_module_vis, menu_vis))

        c["MODULES"].set_user_value("y")
        menu_vis = menu.get_visible_if_visibility()
        verify(menu_vis == module_vis,
               "menu \"{}\" should have 'visible if' visibility '{}' "
               "with modules, has 'visible if' visibility '{}'".
               format(menu.get_title(), module_vis, menu_vis))

    # Ordinary visibility should not affect 'visible if' visibility
    verify_visible_if_visibility(menu_n, "y", "y")
    verify_visible_if_visibility(menu_if_n, "y", "y")
    verify_visible_if_visibility(menu_m, "y", "y")
    verify_visible_if_visibility(menu_if_m, "y", "y")

    verify_visible_if_visibility(menu_visible_if_n, "n", "n")
    verify_visible_if_visibility(menu_visible_if_m, "n", "m")
    verify_visible_if_visibility(menu_visible_if_y, "y", "y")
    verify_visible_if_visibility(menu_visible_if_m_2, "n", "m")

    # Verify that 'visible if' visibility gets propagated to contained symbols
    verify_sym_visibility("VISIBLE_IF_n", "n", "n")
    verify_sym_visibility("VISIBLE_IF_m", "n", "m")
    verify_sym_visibility("VISIBLE_IF_y", "y", "y")
    verify_sym_visibility("VISIBLE_IF_m_2", "n", "m")

    # Comment visibility

    def verify_comment_visibility(comment, no_module_vis, module_vis):
        c["MODULES"].set_user_value("n")
        comment_vis = comment.get_visibility()
        verify(comment_vis == no_module_vis,
               "comment \"{}\" should have visibility '{}' without "
               "modules, has visibility '{}'".
               format(comment.get_text(), no_module_vis, comment_vis))

        c["MODULES"].set_user_value("y")
        comment_vis = comment.get_visibility()
        verify(comment_vis == module_vis,
               "comment \"{}\" should have visibility '{}' with "
               "modules, has visibility '{}'".
               format(comment.get_text(), module_vis, comment_vis))

    comment_n, comment_m, comment_y, comment_if_n, comment_if_m, \
      comment_if_y, comment_m_nested = c.get_comments()

    verify_comment_visibility(comment_n, "n", "n")
    verify_comment_visibility(comment_m, "n", "m")
    verify_comment_visibility(comment_y, "y", "y")
    verify_comment_visibility(comment_if_n, "n", "n")
    verify_comment_visibility(comment_if_m, "n", "m")
    verify_comment_visibility(comment_if_y, "y", "y")
    verify_comment_visibility(comment_m_nested, "n", "m")

    # Verify that string/int/hex symbols with m visibility accept a user value

    assign_and_verify_new_value("STRING_m", "foo bar", "foo bar")
    assign_and_verify_new_value("INT_m", "123", "123")
    assign_and_verify_new_value("HEX_m", "0x123", "0x123")

    #
    # Object relations
    #

    c = kconfiglib.Config("Kconfiglib/tests/Krelation")

    A, B, C, D, E, F, G, H, I = c["A"], c["B"], c["C"], c["D"], c["E"], c["F"],\
                                c["G"], c["H"], c["I"]
    choice_1, choice_2 = c.get_choices()
    verify([menu.get_title() for menu in c.get_menus()] ==
           ["m1", "m2", "m3", "m4"],
           "menu ordering is broken")
    menu_1, menu_2, menu_3, menu_4 = c.get_menus()

    print("Testing object relations...")

    verify(A.get_parent() is None, "A should not have a parent")
    verify(B.get_parent() is choice_1, "B's parent should be the first choice")
    verify(C.get_parent() is choice_1, "C's parent should be the first choice")
    verify(E.get_parent() is menu_1, "E's parent should be the first menu")
    verify(E.get_parent().get_parent() is None,
           "E's grandparent should be None")
    verify(G.get_parent() is choice_2,
           "G's parent should be the second choice")
    verify(G.get_parent().get_parent() is menu_2,
           "G's grandparent should be the second menu")

    #
    # Object fetching (same test file)
    #

    print("Testing object fetching...")

    verify_equals(c.get_symbol("NON_EXISTENT"), None)
    verify(c.get_symbol("A") is A, "get_symbol() is broken")

    verify(c.get_top_level_items() == [A, choice_1, menu_1, menu_3, menu_4],
           "Wrong items at top level")
    verify(c.get_symbols(False) == [A, B, C, D, E, F, G, H, I],
           "get_symbols() is broken")

    verify(choice_1.get_items() == [B, C, D],
           "Wrong get_items() items in 'choice'")
    # Test Kconfig quirk
    verify(choice_1.get_symbols() == [B, D],
           "Wrong get_symbols() symbols in 'choice'")

    verify(menu_1.get_items() == [E, menu_2, I], "Wrong items in first menu")
    verify(menu_1.get_symbols() == [E, I], "Wrong symbols in first menu")
    verify(menu_1.get_items(True) == [E, menu_2, F, choice_2, G, H, I],
           "Wrong recursive items in first menu")
    verify(menu_1.get_symbols(True) == [E, F, G, H, I],
           "Wrong recursive symbols in first menu")
    verify(menu_2.get_items() == [F, choice_2],
           "Wrong items in second menu")
    verify(menu_2.get_symbols() == [F],
           "Wrong symbols in second menu")
    verify(menu_2.get_items(True) == [F, choice_2, G, H],
           "Wrong recursive items in second menu")
    verify(menu_2.get_symbols(True) == [F, G, H],
           "Wrong recursive symbols in second menu")

    #
    # hex/int ranges
    #

    print("Testing hex/int ranges...")

    c = kconfiglib.Config("Kconfiglib/tests/Krange")

    for sym_name in ("HEX_NO_RANGE", "INT_NO_RANGE", "HEX_40", "INT_40"):
        sym = c[sym_name]
        verify(not sym.has_ranges(),
               "{} should not have ranges".format(sym_name))

    for sym_name in ("HEX_ALL_RANGES_DISABLED", "INT_ALL_RANGES_DISABLED",
                     "HEX_RANGE_10_20_LOW_DEFAULT",
                     "INT_RANGE_10_20_LOW_DEFAULT"):
        sym = c[sym_name]
        verify(sym.has_ranges(), "{} should have ranges".format(sym_name))

    # hex/int symbols without defaults should get no default value
    verify_value("HEX_NO_RANGE", "")
    verify_value("INT_NO_RANGE", "")
    # And neither if all ranges are disabled
    verify_value("HEX_ALL_RANGES_DISABLED", "")
    verify_value("INT_ALL_RANGES_DISABLED", "")
    # Make sure they are assignable though, and test that the form of the user
    # value is reflected in the value for hex symbols
    assign_and_verify_new_value("HEX_NO_RANGE", "0x123", "0x123")
    assign_and_verify_new_value("HEX_NO_RANGE", "123", "123")
    assign_and_verify_new_value("INT_NO_RANGE", "123", "123")

    # Defaults outside of the valid range should be clamped
    verify_value("HEX_RANGE_10_20_LOW_DEFAULT", "0x10")
    verify_value("HEX_RANGE_10_20_HIGH_DEFAULT", "0x20")
    verify_value("INT_RANGE_10_20_LOW_DEFAULT", "10")
    verify_value("INT_RANGE_10_20_HIGH_DEFAULT", "20")
    # Defaults inside the valid range should be preserved. For hex symbols,
    # they should additionally use the same form as in the assignment.
    verify_value("HEX_RANGE_10_20_OK_DEFAULT", "0x15")
    verify_value("HEX_RANGE_10_20_OK_DEFAULT_ALTERNATE", "15")
    verify_value("INT_RANGE_10_20_OK_DEFAULT", "15")

    # hex/int symbols with no defaults but valid ranges should default to the
    # lower end of the range if it's > 0
    verify_value("HEX_RANGE_10_20", "0x10")
    verify_value("HEX_RANGE_0_10", "")
    verify_value("INT_RANGE_10_20", "10")
    verify_value("INT_RANGE_0_10", "")
    verify_value("INT_RANGE_NEG_10_10", "")

    # User values and dependent ranges

    def verify_range(sym_name, low, high, default):
        """Tests that the values in the range 'low'-'high' can be assigned, and
        that assigning values outside this range reverts the value back to
        'default' (None if it should revert back to "")."""
        is_hex = (c[sym_name].get_type() == kconfiglib.HEX)
        for i in range(low, high + 1):
            assign_and_verify_new_user_value(sym_name, str(i), str(i))
            if is_hex:
                # The form of the user value should be preserved for hex
                # symbols
                assign_and_verify_new_user_value(sym_name, hex(i), hex(i))

        # Verify that assigning a user value just outside the range causes
        # defaults to be used

        if default is None:
            default_str = ""
        else:
            default_str = hex(default) if is_hex else str(default)

        if is_hex:
            too_low_str = hex(low - 1)
            too_high_str = hex(high + 1)
        else:
            too_low_str = str(low - 1)
            too_high_str = str(high + 1)

        assign_and_verify_new_value(sym_name, too_low_str, default_str)
        assign_and_verify_new_value(sym_name, too_high_str, default_str)

    verify_range("HEX_RANGE_10_20_LOW_DEFAULT",  0x10, 0x20,  0x10)
    verify_range("HEX_RANGE_10_20_HIGH_DEFAULT", 0x10, 0x20,  0x20)
    verify_range("HEX_RANGE_10_20_OK_DEFAULT",   0x10, 0x20,  0x15)

    verify_range("INT_RANGE_10_20_LOW_DEFAULT",  10,   20,    10)
    verify_range("INT_RANGE_10_20_HIGH_DEFAULT", 10,   20,    20)
    verify_range("INT_RANGE_10_20_OK_DEFAULT",   10,   20,    15)

    verify_range("HEX_RANGE_10_20",              0x10, 0x20,  0x10)
    verify_range("HEX_RANGE_0_10",               0x0,  0x10,  None)

    verify_range("INT_RANGE_10_20",              10,  20,     10)
    verify_range("INT_RANGE_0_10",               0,   10,     None)
    verify_range("INT_RANGE_NEG_10_10",          -10, 10,     None)

    # Dependent ranges

    verify_value("HEX_40", "40")
    verify_value("INT_40", "40")

    c["HEX_RANGE_10_20"].unset_user_value()
    c["INT_RANGE_10_20"].unset_user_value()
    verify_value("HEX_RANGE_10_40_DEPENDENT", "0x10")
    verify_value("INT_RANGE_10_40_DEPENDENT", "10")
    c["HEX_RANGE_10_20"].set_user_value("15")
    c["INT_RANGE_10_20"].set_user_value("15")
    verify_value("HEX_RANGE_10_40_DEPENDENT", "0x15")
    verify_value("INT_RANGE_10_40_DEPENDENT", "15")
    c.unset_user_values()
    verify_range("HEX_RANGE_10_40_DEPENDENT", 0x10, 0x40,  0x10)
    verify_range("INT_RANGE_10_40_DEPENDENT", 10,   40,    10)

    #
    # get_referenced_symbols()
    #

    c = kconfiglib.Config("Kconfiglib/tests/Kref")

    # General function for checking get_referenced_symbols() output.
    # Specialized for symbols below.
    def verify_refs(item, refs_no_enclosing, refs_enclosing):
        item_refs = item.get_referenced_symbols()
        item_refs_enclosing = item.get_referenced_symbols(True)

        # For failure messages
        if item.is_symbol():
            item_string = item.get_name()
        elif item.is_choice():
            if item.get_name() is None:
                item_string = "choice"
            else:
                item_string = "choice " + item.get_name()
        elif item.is_menu():
            item_string = 'menu "{}"'.format(item.get_title())
        else:
            # Comment
            item_string = 'comment "{}"'.format(item.get_text())

        verify(len(item_refs) == len(refs_no_enclosing),
               "Wrong number of refs excluding enclosing for {}".
               format(item_string))
        verify(len(item_refs_enclosing) == len(refs_enclosing),
               "Wrong number of refs including enclosing for {}".
               format(item_string))
        for r in [c[name] for name in refs_no_enclosing]:
            verify(r in item_refs,
                   "{} should reference {} when excluding enclosing".
                   format(item_string, r.get_name()))
        for r in [c[name] for name in refs_enclosing]:
            verify(r in item_refs_enclosing,
                   "{} should reference {} when including enclosing".
                   format(item_string, r.get_name()))

    # Symbols referenced by symbols

    def verify_sym_refs(sym_name, refs_no_enclosing, refs_enclosing):
        verify_refs(c[sym_name], refs_no_enclosing, refs_enclosing)

    verify_sym_refs("NO_REF", [], [])
    verify_sym_refs("ONE_REF", ["A"], ["A"])
    own_refs = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L",
                "M", "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X",
                "Y", "Z", "AA"]
    verify_sym_refs("MANY_REF",
      own_refs,
      own_refs + ["IF_REF_1", "IF_REF_2", "MENU_REF_1",
                  "MENU_REF_2"])

    # Symbols referenced by choices

    own_refs = ["CHOICE_REF_4", "CHOICE_REF_5", "CHOICE_REF_6"]
    verify_refs(c.get_choices()[0],
      own_refs,
      own_refs + ["CHOICE_REF_1", "CHOICE_REF_2", "CHOICE_REF_3"])

    # Symbols referenced by menus

    own_refs = ["NO_REF", "MENU_REF_3"]
    verify_refs(c.get_menus()[1],
      own_refs,
      own_refs + ["MENU_REF_1", "MENU_REF_2"])

    # Symbols referenced by comments

    own_refs = ["COMMENT_REF_3", "COMMENT_REF_4", "COMMENT_REF_5"]
    verify_refs(c.get_comments()[0],
      own_refs,
      own_refs + ["COMMENT_REF_1", "COMMENT_REF_2"])

    #
    # get_selected_symbols() (same test file)
    #

    def verify_selects(sym_name, selection_names):
        sym = c[sym_name]
        sym_selections = sym.get_selected_symbols()
        verify(len(sym_selections) == len(selection_names),
               "Wrong number of selects for {}".format(sym_name))
        for sel_name in selection_names:
            sel_sym = c[sel_name]
            verify(sel_sym in sym_selections,
                   "{} should be selected by {}".format(sel_name, sym_name))

    verify_selects("n", [])
    verify_selects("m", [])
    verify_selects("y", [])
    verify_selects("UNAME_RELEASE", [])

    verify_selects("NO_REF", [])
    verify_selects("MANY_REF", ["I", "N"])

    #
    # get_implied_symbols() (same test file)
    #

    def verify_implies(sym_name, imply_names):
        sym = c[sym_name]
        sym_implies = sym.get_implied_symbols()
        verify(len(sym_implies) == len(imply_names),
               "Wrong number of implies for {}".format(sym_name))
        for imply_name in imply_names:
            implied_sym = c[imply_name]
            verify(implied_sym in sym_implies,
                   "{} should be implied by {}".format(imply_name, sym_name))

    verify_implies("n", [])
    verify_implies("m", [])
    verify_implies("y", [])
    verify_implies("UNAME_RELEASE", [])

    verify_implies("NO_REF", [])
    verify_implies("MANY_REF", ["P", "U"])

    #
    # get_defconfig_filename()
    #

    print("Testing get_defconfig_filename()...")

    c = kconfiglib.Config("Kconfiglib/tests/empty")
    verify(c.get_defconfig_filename() is None,
           "get_defconfig_filename() should be None with no defconfig_list "
           "symbol")

    c = kconfiglib.Config("Kconfiglib/tests/Kdefconfig_nonexistent")
    verify(c.get_defconfig_filename() is None,
           "get_defconfig_filename() should be None when none of the files "
           "in the defconfig_list symbol exist")

    # Referenced in Kdefconfig_existent(_but_n)
    os.environ["BAR"] = "defconfig_2"

    c = kconfiglib.Config("Kconfiglib/tests/Kdefconfig_existent_but_n")
    verify(c.get_defconfig_filename() is None,
           "get_defconfig_filename() should be None when the condition is "
           "n for all the defaults")

    c = kconfiglib.Config("Kconfiglib/tests/Kdefconfig_existent")
    verify(c.get_defconfig_filename() == "Kconfiglib/tests/defconfig_2",
           "get_defconfig_filename() should return the existent file "
           "Kconfiglib/tests/defconfig_2")

    #
    # get_mainmenu_text()
    #

    print("Testing get_mainmenu_text()...")

    c = kconfiglib.Config("Kconfiglib/tests/empty")
    verify(c.get_mainmenu_text() is None,
           "An empty Kconfig should not have a mainmenu text")

    # Expanded in the mainmenu text
    os.environ["FOO"] = "bar baz"
    c = kconfiglib.Config("Kconfiglib/tests/Kmainmenu")
    verify(c.get_mainmenu_text() == "---bar baz---",
           "Wrong mainmenu text")

    #
    # Misc. minor APIs
    #

    os.environ["ENV_VAR"] = "foo"
    # Contains reference to undefined environment variable, so disable warnings
    c = kconfiglib.Config("Kconfiglib/tests/Kmisc", print_warnings = False)

    print("Testing is_optional()...")

    verify(not c.get_choices()[0].is_optional(),
           "First choice should not be optional")
    verify(c.get_choices()[1].is_optional(),
           "Second choice should be optional")

    print("Testing get_user_value()...")

    # Avoid warnings from assigning invalid user values and assigning user
    # values to symbols without prompts
    c.set_print_warnings(False)

    syms = [c[name] for name in \
      ("BOOL", "TRISTATE", "STRING", "INT", "HEX")]

    for sym in syms:
        verify(sym.get_user_value() is None,
               "{} should not have a user value to begin with")

    # Assign valid values for the types

    assign_and_verify_new_user_value("BOOL", "n", "n")
    assign_and_verify_new_user_value("BOOL", "y", "y")
    assign_and_verify_new_user_value("TRISTATE", "n", "n")
    assign_and_verify_new_user_value("TRISTATE", "m", "m")
    assign_and_verify_new_user_value("TRISTATE", "y", "y")
    assign_and_verify_new_user_value("STRING", "foo bar", "foo bar")
    assign_and_verify_new_user_value("INT", "123", "123")
    assign_and_verify_new_user_value("HEX", "0x123", "0x123")

    # Assign invalid values for the types. They should retain their old user
    # value.

    assign_and_verify_new_user_value("BOOL", "m", "y")
    assign_and_verify_new_user_value("BOOL", "foo", "y")
    assign_and_verify_new_user_value("BOOL", "1", "y")
    assign_and_verify_new_user_value("TRISTATE", "foo", "y")
    assign_and_verify_new_user_value("TRISTATE", "1", "y")
    assign_and_verify_new_user_value("INT", "foo", "123")
    assign_and_verify_new_user_value("HEX", "foo", "0x123")

    for s in syms:
        s.unset_user_value()
        verify(s.get_user_value() is None,
               "{} should not have a user value after being reset".
               format(s.get_name()))

    print("Testing is_defined()...")

    for sym_name in ("n", "m", "y", "UNAME_RELEASE", "A", "B", "C", "D",
                     "BOOL", "TRISTATE", "STRING", "INT", "HEX"):
        sym = c[sym_name]
        verify(sym.is_defined(),
               "{} should be defined".format(sym_name))

    for sym_name in ("NOT_DEFINED_1", "NOT_DEFINED_2", "NOT_DEFINED_3",
                     "NOT_DEFINED_4"):
        sym = c[sym_name]
        verify(not sym.is_defined(),
               "{} should not be defined".format(sym_name))

    print("Testing is_special()...")

    for sym_name in ("n", "m", "y", "UNAME_RELEASE", "FROM_ENV",
                     "FROM_ENV_MISSING"):
        sym = c[sym_name]
        verify(sym.is_special(),
               "{} should be special".format(sym_name))

    for sym_name in ("A", "B", "C", "D", "BOOL", "TRISTATE", "STRING",
                     "INT", "HEX", "NOT_DEFINED_1", "NOT_DEFINED_2",
                     "NOT_DEFINED_3", "NOT_DEFINED_4"):
        sym = c[sym_name]
        verify(not sym.is_special(),
               "{} should not be special".format(sym_name))

    print("Testing is_from_environment()...")

    for sym_name in ("FROM_ENV", "FROM_ENV_MISSING"):
        sym = c[sym_name]
        verify(sym.is_from_environment(),
               "{} should be from the environment".format(sym_name))

    for sym_name in ("n", "m", "y", "UNAME_RELEASE", "A", "B", "C", "D",
                     "BOOL", "TRISTATE", "STRING", "INT", "HEX",
                     "NOT_DEFINED_1", "NOT_DEFINED_2", "NOT_DEFINED_3",
                     "NOT_DEFINED_4"):
        sym = c[sym_name]
        verify(not sym.is_from_environment(),
               "{} should not be from the environment".format(sym_name))

    print("Testing is_choice_symbol()...")

    for sym_name in ("A", "B", "C", "D"):
        sym = c[sym_name]
        verify(sym.is_choice_symbol(),
               "{} should be a choice symbol".format(sym_name))

    for sym_name in ("n", "m", "y", "UNAME_RELEASE", "Q1", "Q2", "Q3", "BOOL",
                     "TRISTATE", "STRING", "INT", "HEX", "FROM_ENV",
                     "FROM_ENV_MISSING", "NOT_DEFINED_1", "NOT_DEFINED_2",
                     "NOT_DEFINED_3", "NOT_DEFINED_4"):
        sym = c[sym_name]
        verify(not sym.is_choice_symbol(),
               "{} should not be a choice symbol".format(sym_name))

    print("Testing is_allnoconfig_y()...")

    verify(not c["NOT_ALLNOCONFIG_Y"].is_allnoconfig_y(),
           "NOT_ALLNOCONFIG_Y should not be allnoconfig_y")
    verify(c["ALLNOCONFIG_Y"].is_allnoconfig_y(),
           "ALLNOCONFIG_Y should be allnoconfig_y")

    print("Testing UNAME_RELEASE value...")

    verify_value("UNAME_RELEASE", platform.uname()[2])

    # Expansion of environment variables in Config.__init__'s base_dir
    # parameter. Just make sure we don't crash when Kbase_dir 'source's a file
    # from the same directory.

    os.environ["EnV_VaR1"] = "Kconfigl"
    os.environ["EnV_VaR2"] = "ib/tests"
    kconfiglib.Config("Kconfiglib/tests/Kbase_dir",
                      base_dir = "$EnV_VaR1$EnV_VaR2/")

    #
    # .config reading and writing
    #

    print("Testing .config reading and writing...")

    config_test_file = "Kconfiglib/tests/config_test"

    def verify_header(config_name, header):
        c.load_config(config_name)
        verify(c.get_config_header() == header,
               "Expected the header '{}' from '{}', got the header '{}'.".
               format(header, config_name, c.get_config_header()))

    def write_and_verify_header(header):
        c.write_config(config_test_file, header)
        verify_header(config_test_file, header)

    def verify_file_contents(fname, contents):
        with open(fname, "r") as f:
            file_contents = f.read()
            verify(file_contents == contents,
                   "{} contains '{}'. Expected '{}'."
                   .format(fname, file_contents, contents))

    # Writing/reading strings with characters that need to be escaped

    c = kconfiglib.Config("Kconfiglib/tests/Kescape")

    # Test the default value
    c.write_config(config_test_file + "_from_def")
    verify_file_contents(config_test_file + "_from_def",
                         r'''CONFIG_STRING="\"\\"''' "\n")
    # Write our own value
    c["STRING"].set_user_value(r'''\"a'\\''')
    c.write_config(config_test_file + "_from_user")
    verify_file_contents(config_test_file + "_from_user",
                         r'''CONFIG_STRING="\\\"a'\\\\"''' "\n")

    # Read back the two configs and verify the respective values
    c.load_config(config_test_file + "_from_def")
    verify_value("STRING", '"\\')
    c.load_config(config_test_file + "_from_user")
    verify_value("STRING", r'''\"a'\\''')

    # Reading and writing of .config headers

    verify(c.get_config_header() is None,
           "Expected no header before .config loaded, got '{}'".
           format(c.get_config_header()))

    write_and_verify_header("")
    write_and_verify_header(" ")
    write_and_verify_header("\n")
    write_and_verify_header("\n\n")
    write_and_verify_header("#")
    write_and_verify_header("a")
    write_and_verify_header("a\n")
    write_and_verify_header("a\n\n")
    write_and_verify_header("abcdef")
    write_and_verify_header("foo\nbar baz\n\n\n qaz#")

    c.load_config("Kconfiglib/tests/empty")
    verify(c.get_config_header() is None,
           "Expected no header in empty .config, got '{}'".
           format(c.get_config_header()))

    c.load_config("Kconfiglib/tests/config_hash")
    verify(c.get_config_header() == "",
           "Expected empty header in file with just '#', got '{}'".
           format(c.get_config_header()))

    # TODO: Line joining (which stems from _FileFeed reuse) probably doesn't
    # make sense within .config files. (The C implementation has no notion of
    # continuation lines within .config files.) It's harmless except for fairly
    # obscure cases though.
    #
    # Add a test for now just to get test coverage for _FileFeed.peek_next(),
    # which is only used while reading .config files as of writing.

    c.load_config("Kconfiglib/tests/config_continuation")
    verify(c.get_config_header() ==
           " Foo # Bar\n Baz # Foo # Bar\n Baz\n Foo",
           "Continuation line handling within .config headers is broken")

    # Appending values from a .config

    c = kconfiglib.Config("Kconfiglib/tests/Kappend")

    # Values before assigning
    verify_value("BOOL", "n")
    verify_value("STRING", "")

    # Assign BOOL
    c.load_config("Kconfiglib/tests/config_set_bool", replace = False)
    verify_value("BOOL", "y")
    verify_value("STRING", "")

    # Assign STRING
    c.load_config("Kconfiglib/tests/config_set_string", replace = False)
    verify_value("BOOL", "y")
    verify_value("STRING", "foo bar")

    # Reset BOOL
    c.load_config("Kconfiglib/tests/config_set_string")
    verify_value("BOOL", "n")
    verify_value("STRING", "foo bar")

    # Loading a completely empty .config should reset values
    c.load_config("Kconfiglib/tests/empty")
    verify_value("STRING", "")

    # An indented assignment in a .config should be ignored
    c.load_config("Kconfiglib/tests/config_indented")
    verify_value("IGNOREME", "y")

    #
    # get_config()
    #

    print("Testing get_config()...")

    c1 = kconfiglib.Config("Kconfiglib/tests/Kmisc", print_warnings = False)
    c2 = kconfiglib.Config("Kconfiglib/tests/Kmisc", print_warnings = False)

    c1_bool, c1_choice, c1_menu, c1_comment = c1["BOOL"], \
      c1.get_choices()[0], c1.get_menus()[0], c1.get_comments()[0]
    c2_bool, c2_choice, c2_menu, c2_comment = c2["BOOL"], \
      c2.get_choices()[0], c2.get_menus()[0], c2.get_comments()[0]

    verify((c1_bool is not c2_bool) and (c1_choice is not c2_choice) and
           (c1_menu is not c2_menu) and (c1_comment is not c2_comment) and
           (c1_bool.get_config()    is c1) and (c2_bool.get_config()    is c2) and
           (c1_choice.get_config()  is c1) and (c2_choice.get_config()  is c2) and
           (c1_menu.get_config()    is c1) and (c2_menu.get_config()    is c2) and
           (c1_comment.get_config() is c1) and (c2_comment.get_config() is c2),
           "Config instance state separation or get_config() is broken")

    #
    # get_arch/srcarch/srctree/kconfig_filename()
    #

    os.environ["ARCH"] = "ARCH value"
    os.environ["SRCARCH"] = "SRCARCH value"
    os.environ["srctree"] = "srctree value"
    c = kconfiglib.Config("Kconfiglib/tests/Kmisc", print_warnings = False)
    c.load_config("Kconfiglib/tests/empty")

    arch = c.get_arch()
    srcarch = c.get_srcarch()
    srctree = c.get_srctree()
    config_filename = c.get_config_filename()
    kconfig_filename = c.get_kconfig_filename()

    print("Testing get_arch()...")
    verify(arch == "ARCH value",
           "Wrong arch value - got '{}'".format(arch))
    print("Testing get_srcarch()...")
    verify(srcarch == "SRCARCH value",
           "Wrong srcarch value - got '{}'".format(srcarch))
    print("Testing get_srctree()...")
    verify(srctree == "srctree value",
           "Wrong srctree value - got '{}'".format(srctree))
    print("Testing get_config_filename()...")
    verify(config_filename == "Kconfiglib/tests/empty",
           "Wrong config filename - got '{}'".format(config_filename))
    print("Testing get_kconfig_filename()...")
    verify(kconfig_filename == "Kconfiglib/tests/Kmisc",
           "Wrong Kconfig filename - got '{}'".format(kconfig_filename))

    #
    # Choice semantics
    #

    print("Testing choice semantics...")

    c = kconfiglib.Config("Kconfiglib/tests/Kchoice")

    choice_bool, choice_bool_opt, choice_tristate, choice_tristate_opt, \
      choice_bool_m, choice_tristate_m, choice_defaults, \
      choice_no_type_bool, choice_no_type_tristate, \
      choice_missing_member_type_1, choice_missing_member_type_2, \
      choice_weird_syms = c.get_choices()

    for choice in (choice_bool, choice_bool_opt, choice_bool_m,
                   choice_defaults):
        verify(choice.get_type() == kconfiglib.BOOL,
               "choice {} should have type bool".format(choice.get_name()))

    for choice in (choice_tristate, choice_tristate_opt, choice_tristate_m):
        verify(choice.get_type() == kconfiglib.TRISTATE,
               "choice {} should have type tristate"
               .format(choice.get_name()))

    def select_and_verify(sym):
        choice = sym.get_parent()
        sym.set_user_value("y")
        verify(choice.get_mode() == "y",
               'The mode of the choice should be "y" after selecting a '
               "symbol")
        verify(sym.is_choice_selection(),
               "is_choice_selection() should be true for {}"
               .format(sym.get_name()))
        verify(choice.get_selection() is sym,
               "{} should be the selected symbol".format(sym.get_name()))
        verify(choice.get_user_selection() is sym,
               "{} should be the user selection of the choice"
               .format(sym.get_name()))

    def select_and_verify_all(choice):
        choice_syms = choice.get_symbols()
        # Select in forward order
        for sym in choice_syms:
            select_and_verify(sym)
        # Select in reverse order
        for i in range(len(choice_syms) - 1, 0, -1):
            select_and_verify(choice_syms[i])

    def verify_mode(choice, no_modules_mode, modules_mode):
        c["MODULES"].set_user_value("n")
        choice_mode = choice.get_mode()
        verify(choice_mode == no_modules_mode,
               'Wrong mode for choice {} with no modules. Expected "{}", '
               'got "{}".'.format(choice.get_name(), no_modules_mode,
                                   choice_mode))

        c["MODULES"].set_user_value("y")
        choice_mode = choice.get_mode()
        verify(choice_mode == modules_mode,
               'Wrong mode for choice {} with modules. Expected "{}", '
               'got "{}".'.format(choice.get_name(), modules_mode,
                                   choice_mode))

    verify_mode(choice_bool, "y", "y")
    verify_mode(choice_bool_opt, "n", "n")
    verify_mode(choice_tristate, "y", "m")
    verify_mode(choice_tristate_opt, "n", "n")
    verify_mode(choice_bool_m, "n", "y") # Promoted
    verify_mode(choice_tristate_m, "n", "m")

    # Test defaults

    c["TRISTATE_SYM"].set_user_value("n")
    verify(choice_defaults.get_selection_from_defaults() is c["OPT_4"] and
           choice_defaults.get_selection() is c["OPT_4"],
           "Wrong choice default with TRISTATE_SYM = n")
    c["TRISTATE_SYM"].set_user_value("y")
    verify(choice_defaults.get_selection_from_defaults() is c["OPT_2"] and
           choice_defaults.get_selection() is c["OPT_2"],
           "Wrong choice default with TRISTATE_SYM = y")
    c["OPT_1"].set_user_value("y")
    verify(choice_defaults.get_selection_from_defaults() is c["OPT_2"],
           "User selection changed default selection - shouldn't have")
    verify(choice_defaults.get_selection() is c["OPT_1"],
           "User selection should override defaults")

    # Test "y" mode selection

    c["MODULES"].set_user_value("y")

    select_and_verify_all(choice_bool)
    select_and_verify_all(choice_bool_opt)
    select_and_verify_all(choice_tristate)
    select_and_verify_all(choice_tristate_opt)
    # For BOOL_M, the mode should have been promoted
    select_and_verify_all(choice_bool_m)

    # Test "m" mode selection...

    # ...for a choice that can also be in "y" mode

    for sym_name in ("T_1", "T_2"):
        assign_and_verify_new_value(sym_name, "m", "m")
        verify(choice_tristate.get_mode() == "m",
               'Selecting {} to "m" should have changed the mode of the '
               'choice to "m"'.format(sym_name))

        assign_and_verify_new_value(sym_name, "y", "y")
        verify(choice_tristate.get_mode() == "y" and
               choice_tristate.get_selection() is c[sym_name],
               'Selecting {} to "y" should have changed the mode of the '
               'choice to "y" and made it the selection'.format(sym_name))

    # ...for a choice that can only be in "m" mode

    for sym_name in ("TM_1", "TM_2"):
        assign_and_verify_new_value(sym_name, "m", "m")
        assign_and_verify_new_value(sym_name, "n", "n")
        # "y" should be truncated
        assign_and_verify_new_value(sym_name, "y", "m")
        verify(choice_tristate_m.get_mode() == "m",
               'A choice that can only be in "m" mode was not')

    # Verify that choices with no explicitly specified type get the type of the
    # first contained symbol with a type

    verify(choice_no_type_bool.get_type() == kconfiglib.BOOL,
           "Expected first choice without explicit type to have type bool")
    verify(choice_no_type_tristate.get_type() == kconfiglib.TRISTATE,
           "Expected second choice without explicit type to have type "
           "tristate")

    # Verify that symbols without a type in the choice get the type of the
    # choice

    verify((c["MMT_1"].get_type(), c["MMT_2"].get_type(),
            c["MMT_3"].get_type()) ==
             (kconfiglib.BOOL, kconfiglib.BOOL, kconfiglib.TRISTATE),
           "Wrong types for first choice with missing member types")

    verify((c["MMT_4"].get_type(), c["MMT_5"].get_type()) ==
             (kconfiglib.BOOL, kconfiglib.BOOL),
           "Wrong types for second choice with missing member types")

    # Verify that symbols in choices that depend on the preceding symbol aren't
    # considered choice symbols

    def verify_is_normal_choice_symbol(sym):
        verify(sym.is_choice_symbol() and
               sym in choice_weird_syms.get_symbols() and
               sym.get_parent() is choice_weird_syms,
               "{} should be a normal choice symbol".format(sym.get_name()))

    def verify_is_weird_choice_symbol(sym):
        verify(not sym.is_choice_symbol() and
               sym not in choice_weird_syms.get_symbols() and
               sym in choice_weird_syms.get_items() and
               sym.get_parent() is choice_weird_syms,
               "{} should be a weird (non-)choice symbol")

    verify_is_normal_choice_symbol(c["WS1"])
    verify_is_weird_choice_symbol(c["WS2"])
    verify_is_weird_choice_symbol(c["WS3"])
    verify_is_weird_choice_symbol(c["WS4"])
    verify_is_normal_choice_symbol(c["WS5"])
    verify_is_weird_choice_symbol(c["WS6"])

    #
    # Object dependencies
    #

    print("Testing object dependencies...")

    # Note: This tests an internal API

    c = kconfiglib.Config("Kconfiglib/tests/Kdep")

    def verify_dependent(sym_name, deps_names):
        sym = c[sym_name]
        deps = [c[name] for name in deps_names]
        sym_deps = sym._get_dependent()
        verify(len(sym_deps) == len(deps),
               "Wrong number of dependent symbols for {}".format(sym_name))
        verify(len(sym_deps) == len(set(sym_deps)),
               "{}'s dependencies contains duplicates".format(sym_name))
        for dep in deps:
            verify(dep in sym_deps, "{} should depend on {}".
                                    format(dep.get_name(), sym_name))

    # Test twice to cover dependency caching
    for i in range(0, 2):
        n_deps = 37
        # Verify that D1, D2, .., D<n_deps> are dependent on D
        verify_dependent("D", ["D{}".format(i) for i in range(1, n_deps + 1)])
        # Choices
        verify_dependent("A", ["B", "C"])
        verify_dependent("B", ["A", "C"])
        verify_dependent("C", ["A", "B"])
        verify_dependent("S", ["A", "B", "C"])

    # Verify that the last symbol depends on the first in a long chain of
    # dependencies. Test twice to cover dependency caching.

    c = kconfiglib.Config("Kconfiglib/tests/Kchain")

    for i in range(0, 2):
        verify(c["CHAIN_26"] in c["CHAIN_1"]._get_dependent(),
               "Dependency chain broken")

    print("\nAll selftests passed\n" if _all_ok else
          "\nSome selftests failed\n")

def run_compatibility_tests():
    """Runs tests on configurations from the kernel. Tests compability with the
    C implementation by comparing outputs."""

    del os.environ["ARCH"]
    del os.environ["SRCARCH"]
    del os.environ["srctree"]

    if speedy_mode and not os.path.exists("scripts/kconfig/conf"):
        print("\nscripts/kconfig/conf does not exist -- running "
              "'make allnoconfig' to build it...")
        shell("make allnoconfig")

    print("Running compatibility tests...\n")

    # The set of tests that want to run for all architectures in the kernel
    # tree -- currently, all tests. The boolean flag indicates whether .config
    # (generated by the C implementation) should be compared to ._config
    # (generated by us) after each invocation.
    all_arch_tests = [(test_load,           False),
                      (test_config_absent,  True),
                      (test_call_all,       False),
                      (test_all_no,         True),
                      (test_all_yes,        True),
                      (test_all_no_simpler, True),
                      # Needs to report success/failure for each arch/defconfig
                      # combo, hence False.
                      (test_defconfig,      False)]

    arch_srcarch_list = get_arch_srcarch_list()

    for test_fn, compare_configs in all_arch_tests:
        # The test description is taken from the docstring of the corresponding
        # function
        print(textwrap.dedent(test_fn.__doc__))

        for arch, srcarch in arch_srcarch_list:
            rm_configs()

            os.environ["ARCH"] = arch
            os.environ["SRCARCH"] = srcarch
            # Previously we used to load all the arches once and keep them
            # around for the tests. That now uses a huge amount of memory (pypy
            # helps a bit), so reload them for each test instead.
            test_fn(kconfiglib.Config(base_dir = "."))

            # Let kbuild infer SRCARCH from ARCH if we aren't in speedy mode.
            # This could detect issues with the test suite.
            if not speedy_mode:
                del os.environ["SRCARCH"]

            if compare_configs:
                sys.stdout.write("  {:14}".format(arch))
                if equal_confs():
                    print("OK")
                else:
                    print("FAIL")
                    fail()

    if all_ok():
        print("All selftests and compatibility tests passed")
        print(nconfigs, "arch/defconfig pairs tested")
    else:
        print("Some tests failed")

def get_arch_srcarch_list():
    """Returns a list of (ARCH, SRCARCH) tuples to test."""

    res = []

    def add_arch(arch):
        res.append((arch, srcarch))

    for srcarch in os.listdir("arch"):
        if os.path.exists(os.path.join("arch", srcarch, "Kconfig")):
            add_arch(srcarch)
            # Some arches define additional ARCH settings with ARCH != SRCARCH
            # (search for "Additional ARCH settings for" in the Makefile)
            if srcarch == "x86":
                add_arch("i386")
                add_arch("x86_64")
            elif srcarch == "sparc":
                add_arch("sparc32")
                add_arch("sparc64")
            elif srcarch == "sh":
                add_arch("sh64")
            elif srcarch == "tile":
                add_arch("tilepro")
                add_arch("tilegx")

    return res

def test_load(conf):
   """Load all arch Kconfigs to make sure we don't throw any errors"""
   print("  {:14}OK".format(conf.get_arch()))

# The weird docstring formatting is to get the format right when we print the
# docstring ourselves
def test_all_no(conf):
    """
    Verify that our examples/allnoconfig.py script generates the same .config
    as 'make allnoconfig', for each architecture. Runs the script via
    'make scriptconfig', so kinda slow even in speedy mode."""

    # TODO: Support speedy mode for running the script
    shell("make scriptconfig SCRIPT=Kconfiglib/examples/allnoconfig.py "
          "PYTHONCMD='{}'".format(sys.executable))
    shell("mv .config ._config")
    if speedy_mode:
        shell("scripts/kconfig/conf --allnoconfig Kconfig")
    else:
        shell("make allnoconfig")

def test_all_no_simpler(conf):
    """
    Verify that our examples/allnoconfig_simpler.py script generates the same
    .config as 'make allnoconfig', for each architecture. Runs the script via
    'make scriptconfig', so kinda slow even in speedy mode."""

    # TODO: Support speedy mode for running the script
    shell("make scriptconfig SCRIPT=Kconfiglib/examples/allnoconfig_simpler.py "
          "PYTHONCMD='{}'".format(sys.executable))
    shell("mv .config ._config")
    if speedy_mode:
        shell("scripts/kconfig/conf --allnoconfig Kconfig")
    else:
        shell("make allnoconfig")

def test_all_yes(conf):
    """
    Verify that our examples/allyesconfig.py script generates the same .config
    as 'make allyesconfig', for each architecture. Runs the script via
    'make scriptconfig', so kinda slow even in speedy mode."""

    # TODO: Support speedy mode for running the script
    shell("make scriptconfig SCRIPT=Kconfiglib/examples/allyesconfig.py "
          "PYTHONCMD='{}'".format(sys.executable))
    shell("mv .config ._config")
    if speedy_mode:
        shell("scripts/kconfig/conf --allyesconfig Kconfig")
    else:
        shell("make allyesconfig")

def test_call_all(conf):
    """
    Call all public methods on all symbols, menus, choices, and comments for
    all architectures to make sure we never crash or hang. (Nearly all public
    methods: some are hard to test like this, but are exercised by other
    tests.) Also do misc. sanity checks."""
    print("  For {}...".format(conf.get_arch()))

    conf.__str__()
    conf.get_arch()
    conf.get_base_dir()
    conf.get_config_filename()
    conf.get_config_header()
    conf.get_defconfig_filename()
    conf.get_kconfig_filename()
    conf.get_mainmenu_text()
    conf.get_srcarch()
    conf.get_srctree()
    conf.get_symbol("y")
    conf.get_symbols(False)
    conf.get_top_level_items()
    conf.set_print_undef_assign(True)
    conf.set_print_undef_assign(False)
    conf.set_print_warnings(False)
    conf.set_print_warnings(True)
    conf.unset_user_values()

    conf.eval("y && ARCH")

    for s in conf.get_symbols():
        s.__str__()
        s.get_assignable_values()
        s.get_config()
        s.get_help()
        s.get_implied_symbols()
        s.get_lower_bound()
        s.get_name()
        s.get_parent()
        s.get_prompts()
        s.get_ref_locations()
        s.get_referenced_symbols()
        s.get_referenced_symbols(True)
        s.get_selected_symbols()
        s.get_type()
        s.get_upper_bound()
        s.get_user_value()
        s.get_value()
        s.get_visibility()
        s.has_ranges()
        s.is_choice_selection()
        s.is_choice_symbol()
        s.is_defined()
        s.is_from_environment()
        s.is_modifiable()
        s.is_allnoconfig_y()
        s.unset_user_value()

        # Check get_ref/def_location() sanity

        if s.is_special():
            if s.is_from_environment():
                # Special symbols from the environment should have define
                # locations
                verify(s.get_def_locations() != [],
                       "The symbol '{}' is from the environment but lacks "
                       "define locations".format(s.get_name()))
            else:
                # Special symbols that are not from the environment should be
                # defined and have no define locations
                verify(s.is_defined(),
                       "The special symbol '{}' is not defined".
                       format(s.get_name()))
                verify(s.get_def_locations() == [],
                       "The special symbol '{}' has recorded def. locations".
                       format(s.get_name()))
        else:
            # Non-special symbols should have define locations iff they are
            # defined
            if s.is_defined():
                verify(s.get_def_locations() != [],
                       "'{}' defined but lacks recorded locations".
                       format(s.get_name()))
            else:
                verify(s.get_def_locations() == [],
                       "'{}' undefined but has recorded locations".
                       format(s.get_name()))
                verify(s.get_ref_locations() != [],
                       "'{}' both undefined and unreferenced".
                       format(s.get_name()))

    for c in conf.get_choices():
        c.__str__()
        c.get_config()
        c.get_def_locations()
        c.get_help()
        c.get_items()
        c.get_mode()
        c.get_name()
        c.get_parent()
        c.get_prompts()
        c.get_referenced_symbols()
        c.get_referenced_symbols(True)
        c.get_selection()
        c.get_selection_from_defaults()
        c.get_symbols()
        c.get_type()
        c.get_user_selection()
        c.get_visibility()
        c.is_optional()

    for m in conf.get_menus():
        m.__str__()
        m.get_config()
        m.get_items()
        m.get_items(True)
        m.get_location()
        m.get_parent()
        m.get_referenced_symbols()
        m.get_referenced_symbols(True)
        m.get_symbols()
        m.get_symbols(True)
        m.get_title()
        m.get_visibility()
        m.get_visible_if_visibility()

    for c in conf.get_comments():
        c.__str__()
        c.get_config()
        c.get_location()
        c.get_parent()
        c.get_referenced_symbols()
        c.get_referenced_symbols(True)
        c.get_text()
        c.get_visibility()

def test_config_absent(conf):
    """
    Verify that Kconfiglib generates the same .config as 'make alldefconfig',
    for each architecture"""
    conf.write_config("._config")
    if speedy_mode:
        shell("scripts/kconfig/conf --alldefconfig Kconfig")
    else:
        shell("make alldefconfig")

def test_defconfig(conf):
    """
    Verify that Kconfiglib generates the same .config as scripts/kconfig/conf,
    for each architecture/defconfig pair. In obsessive mode, this test includes
    nonsensical groupings of arches with defconfigs from other arches (every
    arch/defconfig combination) and takes an order of magnitude longer time to
    run.

    With logging enabled, this test appends any failures to a file
    test_defconfig_fails in the root."""

    global nconfigs
    defconfigs = []

    def add_configs_for_arch(arch):
        arch_dir = os.path.join("arch", arch)
        # Some arches have a "defconfig" in the root of their arch/<arch>/
        # directory
        root_defconfig = os.path.join(arch_dir, "defconfig")
        if os.path.exists(root_defconfig):
            defconfigs.append(root_defconfig)
        # Assume all files in the arch/<arch>/configs directory (if it
        # exists) are configurations
        defconfigs_dir = os.path.join(arch_dir, "configs")
        if not os.path.exists(defconfigs_dir):
            return
        if not os.path.isdir(defconfigs_dir):
            print("Warning: '{}' is not a directory - skipping"
                  .format(defconfigs_dir))
            return
        for dirpath, _, filenames in os.walk(defconfigs_dir):
            for filename in filenames:
                defconfigs.append(os.path.join(dirpath, filename))

    if obsessive_mode:
        # Collect all defconfigs. This could be done once instead, but it's
        # a speedy operation comparatively.
        for arch in os.listdir("arch"):
            add_configs_for_arch(arch)
    else:
        add_configs_for_arch(conf.get_arch())

    # Test architecture for each defconfig

    for defconfig in defconfigs:
        rm_configs()

        nconfigs += 1

        conf.load_config(defconfig)
        conf.write_config("._config")
        if speedy_mode:
            shell("scripts/kconfig/conf --defconfig='{}' Kconfig".
                  format(defconfig))
        else:
            shell("cp {} .config".format(defconfig))
            # It would be a bit neater if we could use 'make *_defconfig'
            # here (for example, 'make i386_defconfig' loads
            # arch/x86/configs/i386_defconfig' if ARCH = x86/i386/x86_64),
            # but that wouldn't let us test nonsensical combinations of
            # arches and defconfigs, which is a nice way to find obscure
            # bugs.
            shell("make kconfiglibtestconfig")

        sys.stdout.write("  {:14}with {:60} ".
                         format(conf.get_arch(), defconfig))

        if equal_confs():
            print("OK")
        else:
            print("FAIL")
            fail()
            if log_mode:
                with open("test_defconfig_fails", "a") as fail_log:
                    fail_log.write("{}  {} with {} did not match\n"
                            .format(time.strftime("%d %b %Y %H:%M:%S",
                                                  time.localtime()),
                                    conf.get_arch(),
                                    defconfig))

#
# Helper functions
#

devnull = open(os.devnull, "w")

def shell(cmd):
    subprocess.call(cmd, shell = True, stdout = devnull, stderr = devnull)

def rm_configs():
    """Delete any old ".config" (generated by the C implementation) and
    "._config" (generated by us), if present."""
    def rm_if_exists(f):
        if os.path.exists(f):
            os.remove(f)

    rm_if_exists(".config")
    rm_if_exists("._config")

def equal_confs():
    with open(".config") as menu_conf:
        l1 = menu_conf.readlines()

    with open("._config") as my_conf:
        l2 = my_conf.readlines()

    # Skip the header generated by 'conf'
    unset_re = r"# CONFIG_(\w+) is not set"
    i = 0
    for line in l1:
        if not line.startswith("#") or \
           re.match(unset_re, line):
            break
        i += 1

    return l1[i:] == l2

_all_ok = True

def verify(cond, msg):
    """Fails and prints 'msg' if 'cond' is False."""
    if not cond:
        fail(msg)

def verify_equals(x, y):
    """Fails if 'x' does not equal 'y'."""
    if x != y:
        fail("'{}' does not equal '{}'".format(x, y))

def fail(msg = None):
    global _all_ok
    if msg is not None:
        print("Fail: " + msg)
    _all_ok = False

def all_ok():
    return _all_ok

if __name__ == "__main__":
    run_tests()
