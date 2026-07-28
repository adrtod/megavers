"""Tests for megavers.analyze.parse()."""

from megavers.analyze import parse

# ── Fixtures ──────────────────────────────────────────────────────────────────

BASIC = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp notes.txt

Versions of /docs/notes.txt:
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp notes.txt
---- 2     480000 2025-05-10T08:00:00 H:QrStUvWx notes.txt#1746864000
---- 1     460000 2025-03-01T14:00:00 H:YzAbCdEf notes.txt#1740837600
"""

ONE_OLD_VERSION = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 2     512000 2025-07-01T09:00:00 H:IjKlMnOp file.txt

Versions of /docs/file.txt:
---- 2     512000 2025-07-01T09:00:00 H:IjKlMnOp file.txt
---- 1     480000 2025-05-10T08:00:00 H:QrStUvWx file.txt#1746864000
"""

NO_OLD_VERSIONS = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 1     512000 2025-07-01T09:00:00 H:IjKlMnOp single.txt
"""

FILENAME_WITH_SPACES = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 3     100000 2025-07-01T09:00:00 H:AbCdEfGh my report final.pdf

Versions of /docs/my report final.pdf:
---- 3     100000 2025-07-01T09:00:00 H:AbCdEfGh my report final.pdf
---- 2      90000 2025-06-01T08:00:00 H:IjKlMnOp my report final.pdf#1748736000
---- 1      80000 2025-05-01T07:00:00 H:QrStUvWx my report final.pdf#1746057600
"""

TIMESTAMP_SUFFIX = """\
/repo:
FLAGS VERS      SIZE DATE                 NAME
---- 2      39000 2025-07-27T10:24:00 H:FetchHead FETCH_HEAD

Versions of /repo/FETCH_HEAD:
---- 2      39000 2025-07-27T10:24:00 H:FetchHead FETCH_HEAD
---- 1      38000 2025-07-26T10:00:00 H:OldFetch FETCH_HEAD#1753523040
"""

ORPHAN_VERSION_BLOCK = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 1     512000 2025-07-01T09:00:00 H:IjKlMnOp single.txt

Versions of /docs/ghost.txt:
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp ghost.txt
---- 2     480000 2025-05-10T08:00:00 H:QrStUvWx ghost.txt#1746864000
"""

SINGLE_FILE_SCAN_NO_HEADER = """\
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp PLAN.md

Versions of MEGAsync/megavers/PLAN.md:
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp PLAN.md
---- 2     480000 2025-05-10T08:00:00 H:QrStUvWx PLAN.md#1746864000
---- 1     460000 2025-03-01T14:00:00 H:YzAbCdEf PLAN.md#1740837600
"""

HASH_IN_REAL_FILENAME = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 2     512000 2025-07-01T09:00:00 H:IjKlMnOp notes#12345

Versions of /docs/notes#12345:
---- 2     512000 2025-07-01T09:00:00 H:IjKlMnOp notes#12345
---- 1     480000 2025-05-10T08:00:00 H:QrStUvWx notes#12345#1746864000
"""

MISSING_VERSIONS_BLOCK = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp phantom.txt
"""

OUT_OF_ORDER_VERSIONS = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp notes.txt

Versions of /docs/notes.txt:
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp notes.txt
---- 1     460000 2025-03-01T14:00:00 H:YzAbCdEf notes.txt#1740837600
---- 2     480000 2025-05-10T08:00:00 H:QrStUvWx notes.txt#1746864000
"""

STRAY_LINE_MID_BLOCK = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp notes.txt

Versions of /docs/notes.txt:
---- 3     512000 2025-07-01T09:00:00 H:IjKlMnOp notes.txt
Some unexpected warning text here
---- 2     480000 2025-05-10T08:00:00 H:QrStUvWx notes.txt#1746864000
---- 1     460000 2025-03-01T14:00:00 H:YzAbCdEf notes.txt#1740837600
"""

NESTED_DIRS = """\
/parent:
FLAGS VERS      SIZE DATE                 NAME
---- 2     100000 2025-07-01T09:00:00 H:AbCdEfGh top.txt

Versions of /parent/top.txt:
---- 2     100000 2025-07-01T09:00:00 H:AbCdEfGh top.txt
---- 1      90000 2025-06-01T08:00:00 H:IjKlMnOp top.txt#1748736000

/parent/child:
FLAGS VERS      SIZE DATE                 NAME
---- 2      50000 2025-07-01T09:00:00 H:QrStUvWx deep.txt

Versions of /parent/child/deep.txt:
---- 2      50000 2025-07-01T09:00:00 H:QrStUvWx deep.txt
---- 1      45000 2025-06-01T08:00:00 H:YzAbCdEf deep.txt#1748736000
"""

DIRECTORY_ENTRIES = """\
/root:
FLAGS VERS      SIZE DATE                 NAME
drwx 1          - 2025-07-01T09:00:00 H:DirHandle subdir
---- 2     100000 2025-07-01T09:00:00 H:FileHandle file.txt

Versions of /root/file.txt:
---- 2     100000 2025-07-01T09:00:00 H:FileHandle file.txt
---- 1      90000 2025-06-01T08:00:00 H:OldHandle file.txt#1748736000
"""

NO_HANDLES = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 3     512000 2025-07-01T09:00:00 notes.txt

Versions of /docs/notes.txt:
---- 3     512000 2025-07-01T09:00:00 notes.txt
---- 2     480000 2025-05-10T08:00:00 notes.txt#1746864000
---- 1     460000 2025-03-01T14:00:00 notes.txt#1740837600
"""

DECORATIONS = """\
/docs:
|-------|
FLAGS VERS      SIZE DATE                 NAME
---- ---- ---- ----

---- 2     512000 2025-07-01T09:00:00 H:IjKlMnOp file.txt

Versions of /docs/file.txt:
---- 2     512000 2025-07-01T09:00:00 H:IjKlMnOp file.txt

---- 1     480000 2025-05-10T08:00:00 H:QrStUvWx file.txt#1746864000
"""

ROOT_FILE = """\
/:
FLAGS VERS      SIZE DATE                 NAME
---- 2     200000 2025-07-01T09:00:00 H:RootFile root.bin

Versions of //root.bin:
---- 2     200000 2025-07-01T09:00:00 H:RootFile root.bin
---- 1     190000 2025-06-01T08:00:00 H:OldRoot root.bin#1748736000
"""


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_parse_basic_two_old_versions():
    result = parse(BASIC.splitlines())
    assert "/docs/notes.txt" in result
    vf = result["/docs/notes.txt"]
    assert vf.old_count == 2
    assert vf.current_size == 512000
    assert vf.version_size == 480000 + 460000


def test_parse_basic_handles_preserved():
    result = parse(BASIC.splitlines())
    vf = result["/docs/notes.txt"]
    handles = [v.handle for v in vf.old_versions]
    assert "H:QrStUvWx" in handles
    assert "H:YzAbCdEf" in handles


def test_parse_one_old_version():
    result = parse(ONE_OLD_VERSION.splitlines())
    assert "/docs/file.txt" in result
    vf = result["/docs/file.txt"]
    assert vf.old_count == 1
    assert vf.old_versions[0].size == 480000


def test_parse_no_old_versions_excluded():
    result = parse(NO_OLD_VERSIONS.splitlines())
    assert result == {}


def test_parse_filename_with_spaces():
    result = parse(FILENAME_WITH_SPACES.splitlines())
    assert "/docs/my report final.pdf" in result
    vf = result["/docs/my report final.pdf"]
    assert vf.old_count == 2


def test_parse_timestamp_suffix_stripped():
    result = parse(TIMESTAMP_SUFFIX.splitlines())
    assert "/repo/FETCH_HEAD" in result
    vf = result["/repo/FETCH_HEAD"]
    # old version name must not contain #timestamp
    for ov in vf.old_versions:
        assert "#" not in vf.name


def test_parse_orphan_version_block_ignored(capsys):
    # ghost.txt never appeared in directory listing — its versions block must be ignored
    result = parse(ORPHAN_VERSION_BLOCK.splitlines())
    assert "/docs/ghost.txt" not in result
    assert result == {}
    assert "ghost.txt" in capsys.readouterr().err


def test_parse_single_file_scan_no_section_header():
    # Scanning a single file (not a directory) — mega-ls emits no "path:" header,
    # so the path must come from the "Versions of" block, not a directory prefix.
    result = parse(SINGLE_FILE_SCAN_NO_HEADER.splitlines())
    assert "/MEGAsync/megavers/PLAN.md" in result
    assert "/PLAN.md" not in result
    assert result["/MEGAsync/megavers/PLAN.md"].old_count == 2


def test_parse_hash_in_real_filename_not_stripped():
    result = parse(HASH_IN_REAL_FILENAME.splitlines())
    assert "/docs/notes#12345" in result
    assert result["/docs/notes#12345"].name == "notes#12345"


def test_parse_missing_versions_block_warns(capsys):
    # phantom.txt claims 3 versions but no "Versions of" block ever appears for it
    result = parse(MISSING_VERSIONS_BLOCK.splitlines())
    assert result == {}
    assert "phantom.txt" in capsys.readouterr().err


def test_parse_versions_sorted_descending_regardless_of_input_order():
    result = parse(OUT_OF_ORDER_VERSIONS.splitlines())
    vf = result["/docs/notes.txt"]
    assert [v.version_num for v in vf.old_versions] == [2, 1]


def test_parse_stray_line_mid_block_does_not_drop_versions():
    result = parse(STRAY_LINE_MID_BLOCK.splitlines())
    assert "/docs/notes.txt" in result
    assert result["/docs/notes.txt"].old_count == 2


def test_parse_root_file_double_slash_normalized():
    result = parse(ROOT_FILE.splitlines())
    assert "/root.bin" in result
    assert result["/root.bin"].old_count == 1


def test_parse_nested_dirs():
    result = parse(NESTED_DIRS.splitlines())
    assert "/parent/top.txt" in result
    assert "/parent/child/deep.txt" in result
    assert result["/parent/top.txt"].old_count == 1
    assert result["/parent/child/deep.txt"].old_count == 1


def test_parse_directory_entries_skipped():
    result = parse(DIRECTORY_ENTRIES.splitlines())
    # only the file, not the directory
    assert len(result) == 1
    assert "/root/file.txt" in result


def test_parse_no_handles():
    result = parse(NO_HANDLES.splitlines())
    assert "/docs/notes.txt" in result
    vf = result["/docs/notes.txt"]
    assert vf.old_count == 2
    for ov in vf.old_versions:
        assert ov.handle == ""


def test_parse_decoration_lines_skipped():
    result = parse(DECORATIONS.splitlines())
    assert "/docs/file.txt" in result
    vf = result["/docs/file.txt"]
    assert vf.old_count == 1


def test_parse_empty_input():
    assert parse([]) == {}


def test_parse_current_version_not_in_old_versions():
    # The first line of each Versions block is the current version and must be skipped
    result = parse(BASIC.splitlines())
    vf = result["/docs/notes.txt"]
    # current mtime is 2025-07-01; old versions must be older
    for ov in vf.old_versions:
        assert ov.mtime < "2025-07-01T09:00:00"


def test_parse_version_size_property():
    result = parse(BASIC.splitlines())
    vf = result["/docs/notes.txt"]
    assert vf.version_size == sum(v.size for v in vf.old_versions)


def test_parse_oldest_mtime():
    result = parse(BASIC.splitlines())
    vf = result["/docs/notes.txt"]
    assert vf.oldest_mtime == "2025-03-01T14:00:00"


def test_parse_multiple_files_same_dir():
    output = """\
/docs:
FLAGS VERS      SIZE DATE                 NAME
---- 2     100000 2025-07-01T09:00:00 H:Aa alpha.txt
---- 2     200000 2025-07-01T09:00:00 H:Bb beta.txt

Versions of /docs/alpha.txt:
---- 2     100000 2025-07-01T09:00:00 H:Aa alpha.txt
---- 1      90000 2025-06-01T08:00:00 H:Cc alpha.txt#1748736000

Versions of /docs/beta.txt:
---- 2     200000 2025-07-01T09:00:00 H:Bb beta.txt
---- 1     180000 2025-06-01T08:00:00 H:Dd beta.txt#1748736000
"""
    result = parse(output.splitlines())
    assert "/docs/alpha.txt" in result
    assert "/docs/beta.txt" in result
    assert result["/docs/alpha.txt"].old_count == 1
    assert result["/docs/beta.txt"].old_count == 1
