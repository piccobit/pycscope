#!/usr/bin/env python
"""
PyCscope

PyCscope creates a Cscope-like index file for a tree of Python source.
"""

from __future__ import print_function

__author__ = "Peter Portante (peter\x2Ea\x2Eportante\x40gmail\x2Ecom)"
__copyright__ = "Copyright 2012 Peter Portante.  See LICENSE for details."
__date__ = "2012/09/20"
__version__ = "1.1"
__usage__ = """Usage: pycscope.py [-D] [-R] [-S] [-V] [-f reffile] [-i srclistfile] [files ...]

-D              Dump the (C)oncrete (S)yntax (T)ree generated by the parser for each file
-R              Recurse directories for files
-S              Interpret simple strings as symbols
-V              Print version and exit
-f reffile      Use 'reffile' as cross-ref file name instead of 'cscope.out'
-i srclistfile  Use the contents of 'srclistfile' as the list of source files to scan"""

import getopt, sys, os, string, re
import keyword, parser, symbol, token


class Mark(object):
    """ Marks, as defined by Cscope, that are implemented.
    """
    FILE = "@"
    FUNC_DEF = "$"
    FUNC_CALL = "`"
    FUNC_END = "}"
    INCLUDE = "~"       # TODO: assume all includes are global for now
    ASSIGN = "="        # Direct assignment, increment, or decrement
    CLASS = "c"         # Class definition
    GLOBAL = "g"        # Other global definition
    LOCAL = "l"         # Function/block local definition

    # Class private list of valid marks
    __valid = (FILE, FUNC_DEF, FUNC_CALL, FUNC_END, INCLUDE, ASSIGN, CLASS, GLOBAL, LOCAL)

    def __init__(self, mark=''):
        """ Constructor, making sure a given mark is valid.
        """

        if mark:
            assert mark in Mark.__valid, "Not a valid mark (%s)" % mark
        self.__mark = (mark or '')  # Turn None into ''

    def __eq__(self, other):
        return self.__mark == other.__mark

    def __ne__(self, other):
        return self.__mark != other.__mark

    def format(self):
        """ Marks are represented as a string with a tab character
            followed by the mark character itself, if it has
            one. Otherwise it is an empty string.
        """
        if self.__mark:
            return "\t%s" % self.__mark
        else:
            return self.__mark
    __str__ = format

    def __repr__(self):
        return "<Mark:%s>" % self.format().replace("\t", "\\t")

    def __getattr__(self, name):
        """ Used as a way for tests to check the internal value
            without exposing its name directly.
        """
        if name == '_test_mark':
            return self.__mark
        else:
            raise AttributeError(name)

markFuncEnd = Mark(Mark.FUNC_END)

# Get the list of Python keywords and add a few common builtins
kwlist = keyword.kwlist
kwlist.extend(("True", "False", "None"))

strings_as_symbols = False

def main(argv=None):
    """Parse command line args and act accordingly.
    """
    global strings_as_symbols

    if argv is None:
        argv = sys.argv
    # Parse the command line arguments
    try:
        opts, args = getopt.getopt(argv[1:], "DRSVf:i:t:")
    except getopt.GetoptError:
        print(__usage__)
        return 2
    debug = False
    recurse = False
    indexfn = "cscope.out"
    for o, a in opts:
        if o == "-D":
            debug = True
        if o == "-R":
            recurse = True
        if o == "-S":
            strings_as_symbols = True
        if o == "-V":
            # Print version an exit.
            print("pycscope.py: Version %s" % __version__)
            return 0
        if o == "-f":
            indexfn = a
        if o == "-i":
            args.extend(list(map(string.rstrip, open(a, 'r').readlines())))

    # Search current dir by default
    if len(args) == 0:
        args = "."

    # Parse the given list of files/dirs
    basepath = os.getcwd()
    gen = genFiles(basepath, args, recurse)

    indexbuff, fnamesbuff = work(basepath, gen, debug)

    # Symbol data for the last file ends with a file mark
    indexbuff.append("\n%s" % Mark(Mark.FILE))

    if sys.hexversion < 0x03000000:
        fout = open(os.path.join(basepath, indexfn), 'wb')
    else:
        fout = open(os.path.join(basepath, indexfn), 'w', newline='\n')

    writeIndex(basepath, fout, indexbuff, fnamesbuff)
    fout.close()


def writeIndex(basepath, fout, indexbuff, fnamesbuff):
    """Write the index buffer to the output file.
    """
    # Write the header and index
    index = ''.join(indexbuff)
    index_len = len(index)
    hdr_len = len(basepath) + 25
    fout.write("cscope 15 %s -c %010d" % (basepath, hdr_len + index_len))
    fout.write(index)

    # Write trailer info
    fnames = '\n'.join(fnamesbuff) + '\n'
    fout.write("\n1\n.\n0\n")
    fout.write("%d\n" % len(fnamesbuff))
    fout.write("%d\n" % len(fnames))
    fout.write(fnames)


def work(basepath, gen, debug):
    """ The actual work of parsing the files.
    """

    # Create the buffer to store the output (list of strings)
    indexbuff = []
    indexbuff_len = 0
    fnamesbuff = []

    for fname in gen:
        try:
            indexbuff_len = parseFile(basepath, fname, indexbuff, indexbuff_len, fnamesbuff, dump=debug)
        except (SyntaxError, AssertionError) as e:
            print("pycscope.py: %s: Line %s: %s" % (e.filename, e.lineno, e))
            pass

    return indexbuff, fnamesbuff


def isPython(name):
    # Is this a python file?
    return name[-3:] == ".py"


def genFiles(basepath, args, recurse):
    """ A generator for returning all the files that need to be parsed.
        Caller is required to provide synchronization.
    """
    for name in args:
        if os.path.isdir(os.path.join(basepath, name)):
            for fname in parseDir(basepath, name, recurse):
                yield fname
        else:
            # Don't return the file name if it's not python source
            if isPython(name):
                yield name


def parseDir(basepath, relpath, recurse):
    """ A generator that parses all files in the directory and
        recurses into subdirectories if requested.
        Caller is required to provide synchronization.
    """
    dirpath = os.path.join(basepath, relpath)
    for name in os.listdir(dirpath):
        fullpath = os.path.join(dirpath, name)
        if os.path.isdir(fullpath) and recurse:
            for fname in parseDir(basepath, os.path.join(relpath, name), recurse):
                yield fname
        else:
            if isPython(name):
                yield os.path.join(relpath, name)


def parseFile(basepath, relpath, indexbuff, indexbuff_len, fnamesbuff, dump=False):
    """Parses a source file and puts the resulting index into the buffer.
       Caller is required to provide synchronization.
    """
    # Open the file and get the contents
    fullpath = os.path.join(basepath, relpath)
    try:
        f = open(fullpath, 'rU')
    except IOError as e:
        # Can't open a file, emit message and ignore
        print("pycscope.py: %s" % e)
        return indexbuff_len
    filecontents = f.read()
    f.close()

    # Add the file mark to the index
    fnamesbuff.append(relpath)
    indexbuff.append("\n%s%s\n\n" % (Mark(Mark.FILE), relpath))
    indexbuff_len += 1

    # Add path info to any syntax errors in the source files
    if filecontents:
        try:
            indexbuff_len = parseSource(filecontents, indexbuff, indexbuff_len, dump)
        except (SyntaxError, AssertionError) as e:
            e.filename = fullpath
            raise e

    return indexbuff_len

nodeNames = token.tok_name
nodeNames.update(symbol.sym_name)

def replaceNodeType(treeList):
    """ Replaces the 0th element in the list with the name
        that corresponds to its node value.
    """
    global nodeNames

    # Replace node num with name
    treeList[0] = nodeNames[treeList[0]]

    # Recurse
    for i in range(1, len(treeList)):
        if type(treeList[i]) == tuple:
            treeList[i] = list(treeList[i])
        if type(treeList[i]) == list:
            replaceNodeType(treeList[i])
    return treeList

def dumpCst(cst, stream=None):
    """ For debugging, dump in a pretty printed form the concrete syntax tree.
    """
    if type(cst) == tuple:
        cst_l = list(cst)
    else:
        cst_l = cst.tolist(True)

    import pprint, errno
    try:
        pprint.pprint(replaceNodeType(cst_l), stream)
    except IOError as e:
        if e.errno == errno.EPIPE:
            pass
        else:
            raise

    return stream


class Symbol(object):
    """ A representation of a what cscope considers a 'symbol'.
    """
    def __init__(self, name, mark=None):
        """ Constructor, which ensures an actual name ("string") is given.
        """
        assert (mark == Mark.FUNC_END or name) and (type(name) == str), "Must have an actual symbol name as a string (unless marking function end)."

        self.__mark = Mark(mark)
        self.__name = name

    def __add__(self, other):
        """ Add text to the stored name.
        """
        assert other and (isinstance(other, Symbol)), "Must have another Symbol object to concatenate."
        assert self.__mark == other.__mark, "Symbols must be marked the same."
        self.__name += other.__name
        return self
    __iadd__ = __add__

    def format(self):
        """ Explicitly format the values of this object for inclusion
            in the cscope database; for symbols, an optional mark
            precedes it.
        """
        return "%s%s" % (self.__mark, self.__name)
    __str__ = format

    def __repr__(self):
        return "<Symbol:%s>" % self.format()

    def __getattr__(self, name):
        """ Used as a way for tests to check the internal value
            without exposing its name directly.
        """
        if name == '_test_mark':
            return self.__mark._test_mark
        elif name == '_test_name':
            return self.__name
        else:
            print("Symbol(): does not have attribute <%s>" % name)
            raise AttributeError(name)

    def __coerce__(self, other):
        """ We do not implement coercion; we define this routine so
            that the interpretter won't invoke __getattr__() to try to
            find it.
        """
        return NotImplemented

    def __nonzero__(self):
        """ Defined so that the interpretter won't invoke
            __getattr__() to try to find it.
        """
        return True

    def __bool__(self):
        """ Defined so that the interpretter won't invoke
            __getattr__() to try to find it (Python 3).
        """
        return True

    def hasMark(self, mark):
        """ Does this symbol have a given mark?
        """
        return self.__mark == mark


class NonSymbol(object):
    """ A representation of a what cscope considers a 'non-symbol' text.
    """
    def __init__(self, val):
        """ Constructor, whatever we are given we'll store it as a string.
        """
        assert val and (type(val) == str), "Must have an actual string."
        self.__text = str(val)

    def __add__(self, other):
        """ Add text to the stored string.
        """
        assert other and (isinstance(other, NonSymbol)), "Must have another NonSymbol object to concatenate."
        self.__text += ' ' + other.__text
        return self

    def format(self):
        """ Explicitly format the value of this object for inclusion
            in the cscope database; for non-symbol text it is just the
            stored text itself (as is).
        """
        return self.__text
    __str__ = format

    def __repr__(self):
        return "<NonSymbol:%s>" % self.format()


class Line(object):
    def __init__(self, num):
        assert ((type(num) == int) or (type(num) == long)) and num > 0, "Requires a positive, non-zero integer for a line number"
        self.lineno = num
        self.__contents = []    # List of Symbol and NonSymbol objects
        self.__hasSymbol = False

    def __getattr__(self, name):
        """ Used as a way for tests to check the internal value
            without exposing its name directly.
        """
        if name == '_test_contents':
            return self.__contents
        elif name == '_test_hasSymbol':
            return self.__hasSymbol
        else:
            raise AttributeError(name)

    def __add__(self, other):
        ''' Add a Symbol() or a NonSymbol() to the contents of this line
        '''
        assert isinstance(other, Symbol) or isinstance(other, NonSymbol), "Can only add Symbol or NonSymbol objects"

        global markFuncEnd

        if self.__contents and isinstance(other, Symbol) and other.hasMark(markFuncEnd):
            # If we have a function end marker, then we need to make
            # sure it is preceded by a NonSymbol to preserve
            # alternating lines of NonSymbol and then Symbol.
            if isinstance(self.__contents[-1], Symbol):
                self.__contents.append(NonSymbol(' '))
            self.__hasSymbol = True
            self.__contents.append(other)
        elif self.__contents \
                and ((isinstance(self.__contents[-1], NonSymbol) and isinstance(other, NonSymbol))
                     or (isinstance(self.__contents[-1], Symbol) and isinstance(other, Symbol))):
            self.__contents[-1] += other
        else:
            if isinstance(other, Symbol):
                self.__hasSymbol = True
            self.__contents.append(other)
        return self
    __iadd__ = __add__

    def format(self):
        """ Format this source line (that has a symbol) as individual
            strings representing lines in the Cscope database.
        """
        if not self.__hasSymbol:
            return ''

        buff = []
        # Handle the formatting of the initial line number
        item = self.__contents[0]
        if isinstance(item, Symbol):
            # The line number must be placed on its own line, with a
            # trailing blank, when followed by a symbol
            buff.append("%d " % self.lineno)
            buff.append(item.format())
        else:
            assert isinstance(item, NonSymbol)
            # The line number must be placed on the same line as
            # non-symbol text following it
            buff.append("%d %s" % (self.lineno, item.format()))

        # The rest of the contents of the source line are just added
        # as individual lines (strings), preceded by a space
        for i in range(1, len(self.__contents)):
            item = self.__contents[i]
            if isinstance(item, Symbol):
                s = item.format()
                # Add a space to the NonSymbol line so that it
                # displays properly in cscope (only if it doesn't have
                # on already).
                if buff[-1] != ' ':
                    buff[-1] += ' '
            else:
                assert isinstance(item, NonSymbol)
                # Insert a space to the NonSymbol to separate it from
                # the previous Symbol line so that it displays
                # properly in cscope (only if it is not a space
                # itself).
                s = item.format()
                if s != ' ':
                    s = ' ' + s
            buff.append(s)

        # Place each string on its own line, ending the last string
        # with a new line and adding an empty line, per the Cscope
        # spec.
        return "\n".join(buff) + "\n\n"
    __str__ = format

    def __repr__(self):
        return "<Line:%s>" % self.format().replace("\n", "\\n")

    def __coerce__(self, other):
        """ We do not implement coercion; we define this routine so
            that the interpretter won't invoke __getattr___() to try to
            find it.
        """
        return NotImplemented


if sys.hexversion < 0x03000000:
    valid_tokens_for_marks = (token.NAME, token.DOT)
    valid_tokens_for_import = (token.DOT,)
else:
    valid_tokens_for_marks = (token.NAME, token.DOT, token.ELLIPSIS)
    valid_tokens_for_import = (token.DOT, token.ELLIPSIS)


class Context(object):
    ''' Object representing the context for understanding the concrete syntax
        tree (CST) during one single pass.

        The buffer of Line objects with at least one symbol is maintained
        here. The current line is represented as a Line object, where it is
        saved to the buffer if it has at least one Symbol in it.

        This object also maintained a bunch of state to properly interpret CST
        entries as they are encountered.

        Cscope uses Marks to help it understand what a symbol is for. As the
        CST tree is processed, often we'll look ahead into the CST tree to
        associate a Mark with a Symbol before we have processed that
        Symbol. The dictionary of Marks encapsulates that state.
    '''
    # Buffer of lines in the Cscope database (individual strings in a list)
    def __init__(self):
        self.buff = []              # The accumlated list of lines with symbols
        self.line = Line(1)         # The current line being processed
        self.marks = {}             # Association of CST tuples to a Mark
        self.indent_lvl = 0         # Indentation level, used to track outer fn
        self.func_def_lvl = -1      # Function definition level, to track outer
        self.import_cnt = 0         # Number of import statements to expect
        self.import_name = False    # Handling an import ... statement (not from ... import ...)
        self.tests = {}             # List of CST test objects tracked for assignment
        self.power_do_assignment = False

    def setMark(self, tup, mark):
        ''' Add a mark to the dictionary for the given tuple
        '''
        idx = id(tup)
        assert idx not in self.marks
        assert tup[0] in valid_tokens_for_marks, "Expected one of %s, found %s" % ([token.tok_name[t] for t in valid_tokens_for_marks], tup)
        self.marks[idx] = mark

    def getMark(self, tup):
        ''' Get the mark associated with the given tuple. This is a one shot
            deal, as we delete the association from the dictionary to prevent
            unnecessary accumlation of these associations given we never
            rewalk the tree (one pass only).
        '''
        idx = id(tup)
        assert idx in self.marks
        mark = self.marks[idx]
        del(self.marks[idx])
        return mark

    def commit(self, lineno=None):
        ''' Commit a processed souce line to the buffer
        '''
        line = str(self.line)
        if line:
            self.buff.append(line)
        if lineno:
            self.line = Line(lineno)
        else:
            self.line = None


def isNamedFuncCall(cst, cst_len):
    """ Figure out if this CST sub-tree represents a named function call;
        that is, one which looks like name(), or name(arg,arg=1).
    """
    assert (cst[0] == symbol.power)
    if cst_len < 3:
        return False

    return (cst[1][0] == symbol.atom) \
            and (cst[1][1][0] == token.NAME) \
            and (cst[2][0] == symbol.trailer) \
            and (cst[2][1][0] == token.LPAR) \
            and (cst[2][-1][0] == token.RPAR)

def isTrailerFuncCall(cst, idx, cst_len):
    """ Figure out if this CST sub-tree represents a trailer name function
        call; that is, one which looks like name.name(), or
        name.name(arg,arg=1).
    """
    assert (cst[0] == symbol.power)
    assert (idx < (cst_len - 1))

    return (cst[idx][0] == symbol.trailer) \
            and (cst[idx][1][0] == token.DOT) \
            and (cst[idx][2][0] == token.NAME) \
            and (cst[idx + 1][0] == symbol.trailer) \
            and (cst[idx + 1][1][0] == token.LPAR) \
            and (cst[idx + 1][-1][0] == token.RPAR)

def markTestlist(ctx, cst):
    assert (cst[0] == tse)

    for i in range(1, len(cst)):
        # For each test, ... add that CST to the list to
        # track assignments
        if cst[i][0] == token.COMMA:
            continue
        if cst[i][0] not in test_or_star_expr:
            break
        ctx.tests[id(cst[i])] = cst[i]


if sys.hexversion < 0x03000000:
    tse = symbol.testlist
    test_or_star_expr = (symbol.test,)
    testlist_comp = (symbol.testlist_comp, symbol.listmaker)
else:
    tse = symbol.testlist_star_expr
    test_or_star_expr = (symbol.test, symbol.star_expr)
    testlist_comp = (symbol.testlist_comp,)

def processNonTerminal(ctx, cst):
    """ Process a given CST tuple representing a non-terminal symbol
    """
    # We have a non-terminal "symbol"
    if cst[0] == symbol.global_stmt:
        # Handle global declarations
        for i in range(2, len(cst)):
            if not i % 2:
                # Even indices are the names
                assert cst[i][0] == token.NAME
                ctx.setMark(cst[i], Mark.GLOBAL)
    elif cst[0] == symbol.funcdef:
        if ctx.func_def_lvl == -1:
            # Handle function definitions. NOTE: we only mark the
            # outer most function name as a function definition
            # since the cscope utility can't handle nested
            # functions. So all nested function definitions will
            # not be marked as such.
            ctx.func_def_lvl = ctx.indent_lvl
            idx = 1
            if cst[idx][0] == symbol.decorators:
                # Skip the optional decorators under pre-2.7
                # FIXME: verify this is the case.
                idx += 1
            assert (cst[idx][0] == token.NAME) and (cst[idx][1] == 'def')
            idx += 1
            ctx.setMark(cst[idx], Mark.FUNC_DEF)
    elif cst[0] == symbol.decorated \
            and (cst[1][0] == symbol.decorators) \
            and (cst[2][0] == symbol.funcdef):
        # Handle function decorators only.
        dcsts = cst[1]
        for i in range(1, len(dcsts)):
            # Handle each decorator
            dcst = dcsts[i]

            assert dcst[0] == symbol.decorator
            assert dcst[1][0] == token.AT
            assert dcst[2][0] == symbol.dotted_name

            dotted = dcst[2]
            dotted_len = len(dotted)
            assert dotted_len >= 2
            if dotted_len > 2:
                # When decorators use dotted names, but we don't want to
                # consider the entire sequence as the function being called
                # since the functions are not defined that way. Instead, we
                # only mark the last symbol in the sequence as being a
                # function call.
                ctx.setMark(dotted[-1], Mark.FUNC_CALL)
            elif dotted_len == 2:
                # Check for some builtin ones we should ignore
                assert dotted[-1][0] == token.NAME
                if dotted[-1][1] not in ('property', 'classmethod'):
                    ctx.setMark(dotted[-1], Mark.FUNC_CALL)
    elif cst[0] == symbol.import_from:
        # The next tuple is the "from" string, so grab the following dotted
        # name tuple, and mark each NAME and DOT terminal in that tuple list
        # as an include. As they are added to the line they'll be merged into
        # one big symbol marked as an include.
        dnidx = 2
        while cst[dnidx][0] in valid_tokens_for_import:
            dnidx += 1
        if cst[dnidx][0] == symbol.dotted_name:
            for i in range(1, len(cst[dnidx])):
                ctx.setMark(cst[dnidx][i], Mark.INCLUDE)
    elif cst[0] == symbol.import_name:
        # We are dealing with import ... statements, where for dotted name
        # non-terminals it indicates an include module reference
        ctx.import_name = True
    elif cst[0] == symbol.dotted_as_names and ctx.import_name:
        # Figure out how many imports are being performed for:
        #
        #     import a as b, b as c, c as d, ...
        #
        # We use a count so we don't have to walk the tree twice, allowing us
        # to NOT consider the "as foo" as a symbol, only the "dotted" names.
        ctx.import_cnt = len(cst)/2
    elif cst[0] == symbol.dotted_name:
        # Handle dotted names for imports
        if ctx.import_name:
            assert ctx.import_cnt >= 1
            # For imports, we want to collect them all together to form one
            # symbol. To do that, we set each following tuple, which will be
            # NAME, or NAME DOT NAME, etc. to all have INCLUDE marks. As the
            # tree walk continues, these symbols sharing the same mark will be
            # appended to make one continuous name.name.name symbol.,
            for i in range(1, len(cst)):
                ctx.setMark(cst[i], Mark.INCLUDE)
            ctx.import_cnt -= 1
            if ctx.import_cnt == 0:
                ctx.import_name = False
    elif cst[0] == symbol.expr_stmt:
        # Look for assignment statements
        l = len(cst)
        if (l >= 4):
            assert (cst[1][0] == tse)
            if (cst[2][0] == symbol.augassign) and (cst[3][0] in (symbol.testlist, symbol.yield_expr)):
                # testlist or testlist_star_expr, augassign, testlist
                assert cst[1][1][0] == symbol.test, "%s is not symbol.test" % nodeNames[cst[1][1][0]]
                ctx.tests[id(cst[1][1])] = cst[1][1]
            elif (cst[2][0] == token.EQUAL):
                # testlist or testlist_star_expr, EQUAL, ...
                markTestlist(ctx, cst[1])
                for i in range(3, l - 1):
                    if cst[i][0] == token.EQUAL:
                        continue
                    if cst[i][0] != tse:
                        break
                    # We have another testlist, EQUAL, ...
                    markTestlist(ctx, cst[i])
    elif cst[0] in test_or_star_expr:
        if id(cst) in ctx.tests:
            # We happen to have a test CST that is part of an assignment
            # expression of some sort. It is assumed that deep inside this CST
            # subtree is a power CST subtree that is (one of) the target(s) of
            # the assignment to be marked. Since other CST tuples have to be
            # processed in between, we set a flag for the power symbol
            # handling to actually perform the marking.
            assert cst == ctx.tests[id(cst)], "%r(%d) != %r(%d)" % (cst, id(cst), ctx.tests[id(cst)], id(cst))
            del ctx.tests[id(cst)]
            assert not ctx.power_do_assignment
            ctx.power_do_assignment = True
    elif cst[0] == symbol.classdef:
        # Handle class declarations.
        assert (cst[1][0] == token.NAME) and (cst[1][1] == 'class')
        ctx.setMark(cst[2], Mark.CLASS)
    elif cst[0] == symbol.power:
        l_cst = len(cst)
        if ctx.power_do_assignment:
            ctx.power_do_assignment = False
            # power
            #   atom
            #     NAME
            # power
            #   atom
            #     (|[
            #       test
            #       ...
            #     )|]
            if (l_cst == 2) and (cst[1][0] == symbol.atom):
                if len(cst[1]) == 2 and cst[1][1][0] == token.NAME:
                    ctx.setMark(cst[1][1], Mark.ASSIGN)
                elif len(cst[1]) == 4 \
                        and cst[1][1][0] in (token.LPAR, token.LSQB) \
                        and cst[1][2][0] in testlist_comp \
                        and cst[1][3][0] in (token.RPAR, token.RSQB):
                    for i in range(1, len(cst[1][2])):
                        if cst[1][2][i][0] == token.COMMA:
                            continue
                        if cst[1][2][i][0] != symbol.test:
                            break
                        ctx.tests[id(cst[1][2][i])] = cst[1][2][i]

            # power
            #   atom
            #     NAME
            #   trailer
            #     LSQB
            #     subscriptlist
            #     RSQB
            elif l_cst == 3 \
                    and cst[1][0] == symbol.atom \
                    and len(cst[1]) == 2 \
                    and cst[1][ 1][0] == token.NAME \
                    and len(cst[2]) >= 4 \
                    and cst[2][ 0] == symbol.trailer \
                    and cst[2][ 1][0] == token.LSQB \
                    and cst[2][-1][0] == token.RSQB:
                ctx.setMark(cst[1][1], Mark.ASSIGN)

            # power
            #   atom
            #   ...
            #   trailer
            #     DOT
            #     NAME
            elif l_cst >= 3 \
                    and len(cst[-1]) == 3 \
                    and cst[-1][0] == symbol.trailer \
                    and cst[-1][1][0] == token.DOT \
                    and cst[-1][2][0] == token.NAME:
                ctx.setMark(cst[-1][2], Mark.ASSIGN)

            # power
            #   atom
            #   ...
            #   trailer
            #     DOT
            #     NAME
            #   trailer
            #     LSQB
            #     subscriptlist
            #     RSQB
            elif l_cst >= 4 \
                    and len(cst[-2]) == 3 \
                    and cst[-2][0] == symbol.trailer \
                    and cst[-2][1][0] == token.DOT \
                    and cst[-2][2][0] == token.NAME \
                    and len(cst[-1]) >= 4 \
                    and cst[-1][ 0] == symbol.trailer \
                    and cst[-1][ 1][0] == token.LSQB \
                    and cst[-1][-1][0] == token.RSQB:
                ctx.setMark(cst[-2][2], Mark.ASSIGN)

        if isNamedFuncCall(cst, l_cst):
            # Simple named functional call like: name() or name(a,b=1,c)
            ctx.setMark(cst[1][1], Mark.FUNC_CALL)
        for i in range(1, l_cst - 1):
            if isTrailerFuncCall(cst, i, l_cst):
                # Handle named function calls like: name.name() or
                # name.name(a,b=1,c)
                ctx.setMark(cst[i][2], Mark.FUNC_CALL)

def processTerminal(ctx, cst):
    """ Process a given CST tuple representing a terminal symbol
    """
    global kwlist, strings_as_symbols

    # Remember on what line this terminal symbol ended
    lineno = int(cst[2])

    if cst[0] == token.DEDENT:
        # Indentation is not recorded, but still processed. A
        # dedent is handled before we process any line number
        # changes so that we can properly mark the end of a
        # function.
        ctx.indent_lvl -= 1
        if ctx.indent_lvl == ctx.func_def_lvl:
            ctx.func_def_lvl = -1
            ctx.line += Symbol('', Mark.FUNC_END)
        return lineno

    if (lineno != ctx.line.lineno) and (cst[0] != token.STRING):
        # Handle a token on a new line without seeing a NEWLINE
        # token (line continuation with backslash). Skip this for
        # STRINGs so that a display utility can display Python
        # multi-line strings.
        ctx.commit(lineno)

    # Handle tokens
    if cst[0] == token.NEWLINE:
        # Handle new line tokens: we ignore them as a change in
        # the line number for a token will commit a line (or EOF,
        # see below).
        pass
    elif cst[0] == token.INDENT:
        # Indentation is not recorded, but still processed
        ctx.indent_lvl += 1
    elif cst[0] == token.STRING:
        # Handle strings: make sure newline's within strings are
        # escaped.
        if strings_as_symbols \
                and re.search("^('|\"|'''|\"\"\")[A-Za-z_][A-Za-z_0-9]*('|\"|'''|\"\"\")$", cst[1]) is not None:
            # We have a string that is a valid Python identifier, emit a
            # symbol referencer for it enclosed with double square
            # brackets which will show up in the cscope display only.
            ctx.line += NonSymbol("[[")
            ctx.line += Symbol(cst[1])
            ctx.line += NonSymbol("]]")
        else:
            ctx.line += NonSymbol(cst[1].replace("\n", "\\n"))
    elif cst[0] == token.NAME:
        # Handle terminal names, could be a python keyword or
        # user defined symbol, or part of a dotted name sequence.
        if cst[1] in kwlist:
            if id(cst) in ctx.marks:
                # Perhaps print statement used as a function?
                ctx.getMark(cst)
            # Python keywords are treated as non-symbol text
            ctx.line += NonSymbol(cst[1])
        else:
            # Not a python keyword, symbol text
            if id(cst) in ctx.marks:
                s = Symbol(cst[1], ctx.getMark(cst))
            else:
                s = Symbol(cst[1])
            ctx.line += s
    elif (cst[0] == token.DOT) and (id(cst) in ctx.marks):
        # Add the "." to the include symbol, as we are
        # building a larger symbol from all the dotted names
        ctx.line += Symbol(cst[1], ctx.getMark(cst))
    elif token.ISEOF(cst[0]):
        # End of compilation: consume this token without adding it
        # to the line, committing any line being processed.
        ctx.commit()
    else:
        # All other tokens are simply added to the line
        ctx.line += NonSymbol(cst[1])

    return lineno

def walkCst(ctx, cst):
    """ Scan the CST (tuple) for tokens, appending index lines to the buffer.
    """
    indent = 0
    lineno = 1
    stack = [(cst, indent)]
    try:
        while stack:
            cst, indent = stack.pop()

            #print("%5d%s%s" % (lineno, " " * indent, nodeNames[cst[0]]))

            if token.ISNONTERMINAL(cst[0]):
                processNonTerminal(ctx, cst)
            else:
                lineno = processTerminal(ctx, cst)

            indented = False
            for i in range(len(cst)-1, 0, -1):
                if type(cst[i]) == tuple:
                    # Push it onto the processing stack
                    # Mirrors a recursive solution
                    if not indented:
                        indent += 2
                        indented = True
                    stack.append((cst[i], indent))
    except Exception as e:
        e.lineno = lineno
        raise e

def parseSource(sourcecode, indexbuff, indexbuff_len, dump=False):
    """Parses python source code and puts the resulting index information into the buffer.
    """
    if len(sourcecode) == 0:
        return indexbuff_len

    # Parse the source to an Concrete Syntax Tree (cst)
    sourcecode = sourcecode.replace('\r\n', '\n')
    if sourcecode[-1] != '\n':
        # We need to make sure files are terminated by a newline.
        sourcecode += '\n'
    cst = parser.suite(sourcecode)

    if dump:
        dumpCst(cst)

    ctx = Context()

    walkCst(ctx, cst.totuple(True))
    indexbuff.extend(ctx.buff)
    indexbuff_len += len(ctx.buff)
    return indexbuff_len


if __name__ == "__main__":
    sys.exit(main())
