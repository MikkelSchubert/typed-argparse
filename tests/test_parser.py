import argparse
import textwrap
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Generator, List, Optional, Type, TypeVar

import pytest
from typing_extensions import Literal

from typed_argparse import Binding, Parser, SubParser, SubParsers, TypedArgs, param

T = TypeVar("T", bound=TypedArgs)


def parse(arg_type: Type[T], raw_args: List[str]) -> T:
    args = Parser(arg_type).parse_args(raw_args)
    assert isinstance(args, arg_type)
    return args


class ArgparseErrorWrapper:
    def __init__(self) -> None:
        self._error: Optional[argparse.ArgumentError] = None

    @property
    def error(self) -> argparse.ArgumentError:
        assert self._error is not None
        return self._error

    @error.setter
    def error(self, value: argparse.ArgumentError) -> None:
        self._error = value


@contextmanager
def argparse_error() -> Generator[ArgparseErrorWrapper, None, None]:
    # Inspired by:
    # https://stackoverflow.com/a/67107620/1804173

    wrapper = ArgparseErrorWrapper()

    with pytest.raises(SystemExit) as e:
        yield wrapper

    assert isinstance(e.value.__context__, argparse.ArgumentError)
    wrapper.error = e.value.__context__


# Boolean


def test_bool_switch() -> None:
    class Args(TypedArgs):
        verbose: bool

    args = parse(Args, [])
    assert args.verbose is False

    args = parse(Args, ["--verbose"])
    assert args.verbose is True


def test_bool_switch__default_false() -> None:
    class Args(TypedArgs):
        verbose: bool = param(default=False)

    args = parse(Args, [])
    assert args.verbose is False

    args = parse(Args, ["--verbose"])
    assert args.verbose is True


def test_bool_switch__default_true() -> None:
    class Args(TypedArgs):
        no_verbose: bool = param(default=True)

    args = parse(Args, [])
    assert args.no_verbose is True

    args = parse(Args, ["--no-verbose"])
    assert args.no_verbose is False


def test_bool_switch__invalid_default() -> None:
    class Args(TypedArgs):
        verbose: bool = param(default="foo")  # type: ignore

    with pytest.raises(RuntimeError) as e:
        parse(Args, [])

    assert str(e.value) == "Invalid default for bool 'foo'"


# Other scalar types


def test_other_scalar_types() -> None:
    class Args(TypedArgs):
        some_int: int
        some_float: float
        other_int: Optional[int]
        other_float: Optional[float]
        other_int_with_default: int = param(default=43)
        other_float_with_default: float = param(default=2.0)

    args = parse(Args, ["--some-int", "42", "--some-float", "1.0"])
    assert args.some_int == 42
    assert args.some_float == 1.0
    assert args.other_int is None
    assert args.other_float is None
    assert args.other_int_with_default == 43
    assert args.other_float_with_default == 2.0


def test_path() -> None:
    class Args(TypedArgs):
        path: Path

    args = parse(Args, ["--path", "/my/path"])
    assert args.path == Path("/my/path")


# Positional


def test_positional() -> None:
    class Args(TypedArgs):
        file: str = param(positional=True)

    args = parse(Args, ["my_file"])
    assert args.file == "my_file"


def test_positional__with_hyphens() -> None:
    """
    Since argparse does not allow positional arguments to have a `dest` that is different
    from the user-facing parameter, we have an issue: By default we convert the
    positional_with_underscores to positional-with-underscores, because we want the user
    facing variable to have hyphens. Argparse will simply put it in the namespace under that
    spelling. In the validation in TypedArgs, we then look for a variable according to the
    name of the Python annotation, i.e., positional_with_underscores, and thus the lookup
    fails. As a work-around, we currently use a fallback lookup under the 'hyphened' name.
    """

    class Args(TypedArgs):
        positional_with_underscores: str = param(positional=True)

    args = parse(Args, ["foo"])
    assert args.positional_with_underscores == "foo"


# Flags


def test_flags() -> None:
    class Args(TypedArgs):
        file: str = param("-f")

    args = parse(Args, ["-f", "my_file"])
    assert args.file == "my_file"

    args = parse(Args, ["--file", "my_file"])
    assert args.file == "my_file"


def test_flags__renaming() -> None:
    class Args(TypedArgs):
        foo: str = param("--bar")

    args = parse(Args, ["--bar", "bar"])
    assert args.foo == "bar"

    # TODO: Make this work with argparse_error
    with pytest.raises(SystemExit):
        parse(Args, ["--foo", "bar"])


def test_flags__single_char() -> None:
    class Args(TypedArgs):
        x: int = param("-y")

    args = parse(Args, ["-y", "42"])
    assert args.x == 42

    # TODO: Make this work with argparse_error
    with pytest.raises(SystemExit):
        parse(Args, ["-x", "42"])


def test_flags__assert_no_positional_names() -> None:
    class Args(TypedArgs):
        foo: str = param("foo")

    with pytest.raises(ValueError) as e:
        parse(Args, ["foo_value"])

    assert (
        "Invalid flags: ('foo',). All flags should start with '-'. "
        "A positional argument can be created by setting `positional=True`."
    ) == str(e.value)


# Type parser


def test_type_parsers() -> None:
    class ArgsIllegal1(TypedArgs):
        len_of_str: int = param(type=lambda s: "")  # type: ignore

    class ArgsIllegal2(TypedArgs):
        foo: int = param(default="", type=lambda s: len(s))  # type: ignore
        bar: str = param(default="", type=lambda s: len(s))  # type: ignore

    class Args(TypedArgs):
        len_of_str: int = param(positional=True, type=lambda s: len(s))

    assert parse(Args, ["1"]).len_of_str == 1
    assert parse(Args, ["12"]).len_of_str == 2
    assert parse(Args, ["123"]).len_of_str == 3


# Literals


def test_literal() -> None:
    class Args(TypedArgs):
        literal_string: Literal["a", "b"]
        literal_int: Literal[1, 2]

    args = parse(Args, ["--literal-string", "a", "--literal-int", "1"])
    assert args.literal_string == "a"
    assert args.literal_int == 1

    with argparse_error() as e:
        parse(Args, ["--literal-string", "c", "--literal-int", "1"])
    assert "argument --literal-string: invalid choice: 'c' (choose from 'a', 'b')" == str(e.error)

    with argparse_error() as e:
        parse(Args, ["--literal-string", "a", "--literal-int", "3"])
    assert "argument --literal-int: invalid choice: '3' (choose from 1, 2)" == str(e.error)


# Enums


def test_enum() -> None:
    class StrEnum(Enum):
        a = "a"
        b = "b"

    class IntEnum(Enum):
        a = 1
        b = 2

    class Args(TypedArgs):
        enum_string: StrEnum
        enum_int: IntEnum

    args = parse(Args, ["--enum-string", "a", "--enum-int", "a"])
    assert args.enum_string == StrEnum.a
    assert args.enum_int == IntEnum.a

    with argparse_error() as e:
        parse(Args, ["--enum-string", "c", "--enum-int", "a"])
    assert (
        "argument --enum-string: invalid choice: 'c' (choose from <StrEnum.a: 'a'>, <StrEnum.b: 'b'>)"  # noqa
        == str(e.error)
    )

    with argparse_error() as e:
        parse(Args, ["--enum-string", "a", "--enum-int", "c"])
    assert (
        "argument --enum-int: invalid choice: 'c' (choose from <IntEnum.a: 1>, <IntEnum.b: 2>)"
        == str(e.error)
    )


# Subparser


def test_subparser__basic() -> None:
    class FooArgs(TypedArgs):
        x: str

    class BarArgs(TypedArgs):
        y: str

    parser = Parser(
        SubParsers(
            SubParser("foo", FooArgs),
            SubParser("bar", BarArgs),
        )
    )

    args = parser.parse_args(["foo", "--x", "x_value"])
    assert isinstance(args, FooArgs)
    assert args.x == "x_value"

    args = parser.parse_args(["bar", "--y", "y_value"])
    assert isinstance(args, BarArgs)
    assert args.y == "y_value"


def test_subparser__multiple() -> None:
    class FooXA(TypedArgs):
        ...

    class FooXB(TypedArgs):
        ...

    class FooY(TypedArgs):
        ...

    class Bar(TypedArgs):
        ...

    parser = Parser(
        SubParsers(
            SubParser(
                "foo",
                SubParsers(
                    SubParser(
                        "x",
                        SubParsers(
                            SubParser("a", FooXA),
                            SubParser("b", FooXB),
                        ),
                    ),
                    SubParser("y", FooY),
                ),
            ),
            SubParser("bar", Bar),
        )
    )

    args = parser.parse_args(["foo", "x", "a"])
    assert isinstance(args, FooXA)
    args = parser.parse_args(["foo", "x", "b"])
    assert isinstance(args, FooXB)
    args = parser.parse_args(["foo", "y"])
    assert isinstance(args, FooY)
    args = parser.parse_args(["bar"])
    assert isinstance(args, Bar)


# Bindings check


def test_bindings_check() -> None:
    class FooArgs(TypedArgs):
        x: str

    class BarArgs(TypedArgs):
        y: str

    parser = Parser(
        SubParsers(
            SubParser("foo", FooArgs),
            SubParser("bar", BarArgs),
        )
    )

    def foo(foo_args: FooArgs) -> None:
        ...

    def bar(bar_args: BarArgs) -> None:
        ...

    bindings = parser.bind(Binding(FooArgs, foo), Binding(BarArgs, bar))
    assert len(bindings) == 2

    with pytest.raises(ValueError) as e:
        parser.bind(Binding(FooArgs, foo))

    assert "Incomplete bindings: There is no binding for type 'BarArgs'." == str(e.value)


# Run


def test_parser_run() -> None:
    class Args(TypedArgs):
        verbose: bool

    was_executed = False

    def runner(args: Args) -> None:
        nonlocal was_executed
        was_executed = True
        assert args.verbose

    Parser(Args).run(
        lambda parser: parser.bind(Binding(Args, runner)),
        raw_args=["--verbose"],
    )

    assert was_executed


# Misc


def test_forwarding_of_argparse_kwargs(capsys: pytest.CaptureFixture[str]) -> None:
    class Args(TypedArgs):
        verbose: bool

    parser = Parser(
        Args,
        prog="my_prog",
        usage="my_usage",
        description="my description",
        epilog="my epilog",
    )
    with pytest.raises(SystemExit):
        parser.parse_args(["-h"])

    captured = capsys.readouterr()
    assert captured.out == textwrap.dedent(
        """\
        usage: my_usage

        my description

        optional arguments:
          -h, --help  show this help message and exit
          --verbose

        my epilog
        """
    )


def test_readability_of_parser_structures() -> None:
    class FooArgs(TypedArgs):
        x: str

    class BarArgs(TypedArgs):
        y: str

    parser = Parser(
        SubParsers(
            SubParser("foo", FooArgs),
            SubParser("bar", BarArgs),
        )
    )
    expected = "Parser(SubParsers(SubParser('foo', FooArgs), SubParser('bar', BarArgs)))"
    assert str(parser) == expected
    assert repr(parser) == expected

    parser = Parser(FooArgs)
    expected = "Parser(FooArgs)"
    assert str(Parser(FooArgs)) == "Parser(FooArgs)"
    assert repr(Parser(FooArgs)) == "Parser(FooArgs)"


def test_illegal_param_type() -> None:
    class Args(TypedArgs):
        foo: str = "default"

    with pytest.raises(RuntimeError) as e:
        Parser(Args).parse_args([])

    assert "Class attribute 'foo' of type str isn't of type Param." in str(e.value)
