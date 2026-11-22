from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
import sqlite3


@contextmanager
def open_ledger(path):
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys = ON')
        yield db
    finally:
        db.close()


def initialize(db):
    if db.in_transaction:
        raise ValueError('initialize requires a connection outside a transaction')
    schema = Path(__file__).with_name('schema.sql').read_text(encoding='utf-8')
    try:
        db.executescript(schema)
    except BaseException:
        db.rollback()
        raise


@contextmanager
def write_transaction(db):
    if db.in_transaction:
        db.execute('SAVEPOINT ledger_write')
        try:
            yield
            db.execute('RELEASE ledger_write')
        except BaseException:
            if db.in_transaction:
                db.execute('ROLLBACK TO ledger_write')
                db.execute('RELEASE ledger_write')
            raise
        return
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


@contextmanager
def read_snapshot(db):
    if db.in_transaction:
        yield
        return
    db.execute('BEGIN')
    try:
        yield
    finally:
        db.rollback()


def require_transaction(db):
    if not db.in_transaction:
        raise ValueError('storage operation requires a transaction')


def identifier(value, field):
    if type(value) is not str or not value or value.strip() != value or '\x00' in value:
        raise ValueError(f'{field} must be a nonempty identifier')
    value.encode('utf-8')
    return value


def integer(value, field):
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise ValueError(f'{field} must be a signed 64-bit integer')
    return value


def ordered(value, field):
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray, memoryview)):
        raise ValueError(f'{field} must be an ordered sequence')
    return tuple(value)


def pair(value, field):
    items = ordered(value, field)
    if len(items) != 2:
        raise ValueError(f'{field} must contain two entries')
    return items


def keyed(value, field):
    entries = value.items() if isinstance(value, Mapping) else ordered(value, field)
    result = {}
    for entry in entries:
        key, item = pair(entry, field)
        identifier(key, field)
        if key in result:
            raise ValueError(f'duplicate {field} key: {key}')
        result[key] = item
    return result


def encode_fraction(value):
    numerator = str(Decimal(value.numerator))
    denominator = str(Decimal(value.denominator))
    return f'{numerator}/{denominator}'


def decode_fraction(value):
    numerator, denominator = value.split('/')
    return Fraction(int(Decimal(numerator)), int(Decimal(denominator)))
